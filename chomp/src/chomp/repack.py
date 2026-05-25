"""
repack.py — Core rewrite/internalize logic.

Modes
-----
  rewrite    : Replace installer URLs with internal server URLs.
  internalize: Embed installers inside the nupkg under files/.
               Mirrors `choco download --internalize` behavior.

Pipeline
--------
  Phase 1  extract → rewrite URLs in .ps1 → repack → out/
  Phase 2  download installers
  Phase 2b patch checksums + embed files (internalize) → repack
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
    r"""
    (?:-Checksum(?P<slot64a>64)?|\$checksum(?P<slot64b>64)?|\bChecksum(?P<slot64c>64)?)
    \s*(?:=\s*)?["\']?(?P<hex>[0-9a-fA-F]{32,128})["\']?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SKIP_PATTERNS = [
    (re.compile(r"[<>{}|\\^`\[\]]"), "invalid URI chars"),
    (re.compile(r"\$[a-zA-Z]"), "PowerShell variable"),
    (re.compile(r"\.\.\."), "ellipsis/truncated URL"),
    (re.compile(r"#"), "URL fragment"),
]

_INSTALLER_EXTS = {
    ".exe",
    ".msi",
    ".msu",
    ".msp",
    ".msix",
    ".appx",
    ".zip",
    ".7z",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".cab",
    ".iso",
    ".img",
    ".dmg",
    ".nupkg",
    ".vsix",
    ".jar",
    ".ps1",
    ".psm1",
}

_INTERNALIZE_REF = (
    r"$(Split-Path -parent $MyInvocation.MyCommand.Definition)\files\{filename}"
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pkg_id_version(nupkg: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(nupkg) as z:
            specs = [n for n in z.namelist() if n.endswith(".nuspec")]
            if not specs:
                return _split_stem(nupkg.stem)
            with z.open(specs[0]) as f:
                tree = ET.parse(f)
        root = tree.getroot()
        ns = root.tag[1 : root.tag.index("}")] if root.tag.startswith("{") else ""
        t = lambda n: f"{{{ns}}}{n}" if ns else n
        meta = tree.find(t("metadata"))
        pid = (meta.findtext(t("id")) or "").strip()
        ver = (meta.findtext(t("version")) or "").strip()
        if pid and ver:
            return pid, ver
    except Exception:
        pass
    return _split_stem(nupkg.stem)


def _split_stem(stem: str) -> tuple[str, str]:
    parts = stem.split(".")
    for i, p in enumerate(parts):
        if re.match(r"^\d+$", p) and i > 0:
            return ".".join(parts[:i]), ".".join(parts[i:])
    return stem, ""


def _filename_from_url(url: str) -> str:
    name = Path(urlparse(url).path).name
    return name if name else "installer.bin"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_url(url: str) -> tuple[bool, str]:
    for pat, reason in _SKIP_PATTERNS:
        if pat.search(url):
            return False, reason
    parsed = urlparse(url)
    if not parsed.hostname or parsed.hostname in ("", "localhost"):
        return False, "no valid hostname"
    ext = Path(parsed.path).suffix.lower()
    if not ext:
        return False, "no file extension"
    if ext not in _INSTALLER_EXTS:
        return False, f"not an installer extension ({ext!r})"
    return True, ""


# ── Zip helpers ───────────────────────────────────────────────────────────────


def _extract(nupkg: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(nupkg) as z:
        z.extractall(dest)
    vlog(f"Extracted {nupkg.name} → {dest}")


def _repack(source_dir: Path, dest_nupkg: Path) -> None:
    """Atomically repack source_dir into dest_nupkg via a .tmp sibling."""
    dest_nupkg.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_nupkg.with_suffix(".nupkg.tmp")
    tmp.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in source_dir.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(source_dir))
        tmp.replace(dest_nupkg)  # atomic on same filesystem
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    vlog(f"Repacked → {dest_nupkg}")


# ── URL rewriting ─────────────────────────────────────────────────────────────


def _rewrite_ps1(
    ps1: Path, pkg_name: str, pkg_version: str, mode: str, base_url: str = None
) -> list[dict]:
    text = ps1.read_text(encoding="utf-8", errors="replace")
    mappings = []
    sub = f"{pkg_name}/{pkg_version}" if pkg_version else pkg_name

    for match in URL_RE.finditer(text):
        old_url = match.group()
        filename = _filename_from_url(old_url)
        new_url = (
            _INTERNALIZE_REF.format(filename=filename)
            if mode == "internalize"
            else f"{base_url.rstrip('/')}/{sub}/{filename}"
        )
        if old_url != new_url:
            mappings.append(
                {
                    "package": pkg_name,
                    "version": pkg_version,
                    "ps1": ps1.name,
                    "old_url": old_url,
                    "new_url": new_url,
                    "filename": filename,
                    "mode": mode,
                    "checksum_patched": False,
                    "new_checksum": None,
                }
            )

    if mappings:
        new_text = text
        for m in mappings:
            new_text = new_text.replace(m["old_url"], m["new_url"])
        if new_text != text:
            ps1.write_text(new_text, encoding="utf-8")
            vlog(f"Rewrote {len(mappings)} URL(s) in {ps1.name} [{mode}]")
    return mappings


# ── Checksum patching ─────────────────────────────────────────────────────────


def _patch_checksums_ps1(ps1: Path, mappings: list[dict], local_file_resolver) -> None:
    text = ps1.read_text(encoding="utf-8", errors="replace")
    changed = False
    checksums = list(_CHECKSUM_RE.finditer(text))

    for mapping in mappings:
        local_file = local_file_resolver(mapping)
        if not local_file or not local_file.exists():
            vlog(f"  skip checksum (file not found): {local_file}")
            continue

        search_term = mapping["new_url"]
        url_pos = text.find(search_term)
        if url_pos == -1:
            url_pos = text.find(mapping["filename"])
        if url_pos == -1:
            vlog(f"  skip checksum (ref not found): {search_term}")
            continue

        is_64 = "64" in mapping["filename"]
        same_slot = [
            m
            for m in checksums
            if bool(re.search(r"64", m.group(), re.IGNORECASE)) == is_64
        ]
        if not same_slot:
            vlog(
                f"  no checksum slot for {'64-bit' if is_64 else '32-bit'} in {ps1.name}"
            )
            continue

        best = min(same_slot, key=lambda m: abs(m.start() - url_pos))
        new_hash = _sha256(local_file)
        vlog(f"  patching checksum: {best.group('hex')[:8]}… → {new_hash[:8]}…")
        text = text[: best.start("hex")] + new_hash + text[best.end("hex") :]
        checksums = list(_CHECKSUM_RE.finditer(text))
        mapping["checksum_patched"] = True
        mapping["new_checksum"] = new_hash
        changed = True

    if changed:
        ps1.write_text(text, encoding="utf-8")


# ── High-level pipelines ──────────────────────────────────────────────────────


def collect_urls(
    nupkg: Path,
    base_url: str | None,
    out_dir: Path,
    mode: str,
    force: bool = False,
) -> list[dict] | None:
    """
    Scan a nupkg's .ps1 scripts and return URL mappings (no disk writes).

    Returns None if out_dir/<nupkg.name> already exists and force=False.
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
            ps1_name = Path(entry).name
            for match in URL_RE.finditer(text):
                old_url = match.group()
                filename = _filename_from_url(old_url)
                new_url = (
                    _INTERNALIZE_REF.format(filename=filename)
                    if mode == "internalize"
                    else f"{base_url.rstrip('/')}/{sub}/{filename}"
                )
                if old_url != new_url:
                    mappings.append(
                        {
                            "package": pkg_name,
                            "version": pkg_version,
                            "ps1": ps1_name,
                            "old_url": old_url,
                            "new_url": new_url,
                            "filename": filename,
                            "mode": mode,
                            "checksum_patched": False,
                            "new_checksum": None,
                        }
                    )
    return mappings


def build_nupkg(
    nupkg: Path,
    mappings: list[dict],
    local_file_resolver,
    out_dir: Path,
    work_dir: Path,
    mode: str,
) -> None:
    """
    Extract nupkg, rewrite URLs, embed installers, patch checksums, repack to out_dir.

    out_dir/<nupkg.name> is written atomically via _repack's internal .tmp rename.
    The extract dir is always cleaned up, success or failure.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = work_dir / nupkg.stem
    try:
        _extract(nupkg, extract_dir)
        for ps1 in extract_dir.rglob("*.ps1"):
            ps1_maps = [m for m in mappings if m["ps1"] == ps1.name]
            if not ps1_maps:
                continue
            # Rewrite URLs
            text = ps1.read_text(encoding="utf-8", errors="replace")
            for m in ps1_maps:
                text = text.replace(m["old_url"], m["new_url"])
            ps1.write_text(text, encoding="utf-8")
            # Embed installer files (internalize only)
            if mode == "internalize":
                files_dir = ps1.parent / "files"
                files_dir.mkdir(exist_ok=True)
                for m in ps1_maps:
                    src = local_file_resolver(m)
                    if src and src.exists():
                        dst = files_dir / m["filename"]
                        if not dst.exists():
                            shutil.copy2(src, dst)
                            vlog(
                                f"  embedded {m['filename']} → {files_dir.relative_to(extract_dir)}/"
                            )
            # Patch checksums
            _patch_checksums_ps1(ps1, ps1_maps, local_file_resolver)
        _repack(extract_dir, out_dir / nupkg.name)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
