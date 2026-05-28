"""
repack.py — Core rewrite/internalize logic (the only two modes differ in just
two places: the replacement reference written into the script, and whether the
installer is embedded inside the .nupkg).

  rewrite     : replace installer URLs with internal-server URLs.
  internalize : embed installers under tools/files/ and reference them locally
                (mirrors `choco download --internalize`).

Pipeline
--------
  scan (collect_urls)  → read-only: map every installer URL to its replacement.
  download (download.py)
  build (build_nupkg)  → extract → rewrite scripts → embed (internalize) →
                         patch checksums → repack atomically.
"""

import hashlib
import re
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from .term import vlog

# ── Patterns ──────────────────────────────────────────────────────────────────

URL_RE = re.compile(r'https?://[^\s"\'`<>]+')

_CHECKSUM_RE = re.compile(
    r"""(?:-Checksum(?P<a>64)?|\$checksum(?P<b>64)?|\bChecksum(?P<c>64)?)
        \s*(?:=\s*)?["\']?(?P<hex>[0-9a-fA-F]{32,128})["\']?""",
    re.IGNORECASE | re.VERBOSE,
)

_SKIP_PATTERNS = [
    (re.compile(r"[<>{}|\\^`\[\]]"), "invalid URI chars"),
    (re.compile(r"\$[a-zA-Z]"), "PowerShell variable"),
    (re.compile(r"\.\.\."), "ellipsis/truncated URL"),
    (re.compile(r"#"), "URL fragment"),
]

_INSTALLER_EXTS = {
    ".exe", ".msi", ".msu", ".msp", ".msix", ".appx", ".zip", ".7z", ".tar",
    ".gz", ".bz2", ".xz", ".cab", ".iso", ".img", ".dmg", ".nupkg", ".vsix",
    ".jar", ".ps1", ".psm1",
}

_INTERNALIZE_REF = r"$(Split-Path -parent $MyInvocation.MyCommand.Definition)\files\{filename}"


# ── Small helpers ─────────────────────────────────────────────────────────────


def _filename_from_url(url: str) -> str:
    return Path(urlparse(url).path).name or "installer.bin"


def _new_ref(filename: str, mode: str, base_url: str | None, sub: str) -> str:
    """Replacement reference for an installer, per mode."""
    if mode == "internalize":
        return _INTERNALIZE_REF.format(filename=filename)
    return f"{base_url.rstrip('/')}/{sub}/{filename}"


def _replace_url_in_text(text: str, old_url: str, new_url: str) -> str:
    """
    Replace old_url with new_url. If new_url contains a PowerShell subexpression
    ``$(...)``, re-quote any single-quoted occurrence with double quotes so it
    expands at runtime (single-quoted PS strings are literal).
    """
    if "$(" in new_url:
        text = text.replace(f"'{old_url}'", f'"{new_url}"')
    return text.replace(old_url, new_url)


def _split_stem(stem: str) -> tuple[str, str]:
    parts = stem.split(".")
    for i, p in enumerate(parts):
        if i > 0 and re.match(r"^\d+$", p):
            return ".".join(parts[:i]), ".".join(parts[i:])
    return stem, ""


def _pkg_id_version(nupkg: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(nupkg) as z:
            specs = [n for n in z.namelist() if n.endswith(".nuspec")]
            if not specs:
                return _split_stem(nupkg.stem)
            with z.open(specs[0]) as f:
                root = ET.parse(f).getroot()
        ns = root.tag[1 : root.tag.index("}")] if root.tag.startswith("{") else ""
        t = lambda n: f"{{{ns}}}{n}" if ns else n
        meta = root.find(t("metadata"))
        pid = (meta.findtext(t("id")) or "").strip()
        ver = (meta.findtext(t("version")) or "").strip()
        if pid and ver:
            return pid, ver
    except Exception:
        pass
    return _split_stem(nupkg.stem)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_url(url: str) -> tuple[bool, str]:
    """(downloadable, reason) — is this a real installer file URL?"""
    for pat, reason in _SKIP_PATTERNS:
        if pat.search(url):
            return False, reason
    parsed = urlparse(url)
    if not parsed.hostname or parsed.hostname == "localhost":
        return False, "no valid hostname"
    ext = Path(parsed.path).suffix.lower()
    if not ext:
        return False, "no file extension"
    if ext not in _INSTALLER_EXTS:
        return False, f"not an installer extension ({ext!r})"
    return True, ""


# ── Zip helpers ───────────────────────────────────────────────────────────────


def _repack(source_dir: Path, dest_nupkg: Path) -> None:
    """Atomically repack source_dir → dest_nupkg via a .tmp sibling."""
    dest_nupkg.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_nupkg.with_suffix(".nupkg.tmp")
    tmp.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in source_dir.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(source_dir))
        tmp.replace(dest_nupkg)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    vlog(f"Repacked → {dest_nupkg}")


# ── Checksum patching ─────────────────────────────────────────────────────────


def _patch_checksums_ps1(ps1: Path, mappings: list[dict], resolver) -> None:
    text = ps1.read_text(encoding="utf-8", errors="replace")
    changed = False
    checksums = list(_CHECKSUM_RE.finditer(text))

    for m in mappings:
        local = resolver(m)
        if not local or not local.exists():
            vlog(f"  skip checksum (file not found): {local}")
            continue
        pos = text.find(m["new_url"])
        if pos == -1:
            pos = text.find(m["filename"])
        if pos == -1:
            continue
        is_64 = "64" in m["filename"]
        slot = [c for c in checksums if bool(re.search("64", c.group(), re.I)) == is_64]
        if not slot:
            vlog(f"  no {'64' if is_64 else '32'}-bit checksum slot in {ps1.name}")
            continue
        best = min(slot, key=lambda c: abs(c.start() - pos))
        new_hash = _sha256(local)
        vlog(f"  patching checksum: {best.group('hex')[:8]}… → {new_hash[:8]}…")
        text = text[: best.start("hex")] + new_hash + text[best.end("hex") :]
        checksums = list(_CHECKSUM_RE.finditer(text))
        m["checksum_patched"], m["new_checksum"] = True, new_hash
        changed = True

    if changed:
        ps1.write_text(text, encoding="utf-8")


# ── Pipeline ──────────────────────────────────────────────────────────────────


def collect_urls(nupkg: Path, base_url, out_dir: Path, mode: str, force: bool = False):
    """
    Scan a nupkg's .ps1 scripts and return URL→replacement mappings (no writes).
    Returns None if out_dir/<nupkg.name> already exists and not force.
    """
    if (out_dir / nupkg.name).exists() and not force:
        vlog(f"  skip (exists): {nupkg.name}")
        return None

    pkg_name, pkg_version = _pkg_id_version(nupkg)
    sub = f"{pkg_name}/{pkg_version}" if pkg_version else pkg_name
    mappings = []
    with zipfile.ZipFile(nupkg) as z:
        for entry in z.namelist():
            if not entry.endswith(".ps1"):
                continue
            text = z.read(entry).decode("utf-8", errors="replace")
            for match in URL_RE.finditer(text):
                old_url = match.group()
                filename = _filename_from_url(old_url)
                new_url = _new_ref(filename, mode, base_url, sub)
                if old_url != new_url:
                    mappings.append(
                        {
                            "package": pkg_name,
                            "version": pkg_version,
                            "ps1": Path(entry).name,
                            "old_url": old_url,
                            "new_url": new_url,
                            "filename": filename,
                            "mode": mode,
                            "checksum_patched": False,
                            "new_checksum": None,
                        }
                    )
    return mappings


def build_nupkg(nupkg, mappings, local_file_resolver, out_dir, work_dir, mode):
    """Extract → rewrite URLs → embed (internalize) → patch checksums → repack."""
    out_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = work_dir / nupkg.stem
    try:
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(nupkg) as z:
            z.extractall(extract_dir)
        vlog(f"Extracted {nupkg.name}")

        for ps1 in extract_dir.rglob("*.ps1"):
            ps1_maps = [m for m in mappings if m["ps1"] == ps1.name]
            if not ps1_maps:
                continue
            text = ps1.read_text(encoding="utf-8", errors="replace")
            for m in ps1_maps:
                text = _replace_url_in_text(text, m["old_url"], m["new_url"])
            ps1.write_text(text, encoding="utf-8")

            if mode == "internalize":
                files_dir = ps1.parent / "files"
                files_dir.mkdir(exist_ok=True)
                for m in ps1_maps:
                    src = local_file_resolver(m)
                    if src and src.exists():
                        dst = files_dir / m["filename"]
                        if not dst.exists():
                            shutil.copy2(src, dst)
                            vlog(f"  embedded {m['filename']}")

            _patch_checksums_ps1(ps1, ps1_maps, local_file_resolver)

        _repack(extract_dir, out_dir / nupkg.name)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
