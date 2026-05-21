"""
fetch.py — HTTP helpers + Chocolatey NuGet v2 resolver/downloader.

Two backends (--pwsh flag):
  Python  (default) — urllib.request, no third-party deps
  PowerShell        — Invoke-WebRequest; works through corp proxies
"""

import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

from .term import CHECK, CROSS, DL, SKIP, Spinner, dim, err, ok
from .term import pkg as cpkg
from .term import vlog, vlog_http, vlog_pwsh

_CHOCO_API = "https://community.chocolatey.org/api/v2"
_USER_AGENT = "NuGet/6.0 (Microsoft Windows NT 10.0; chomp)"


# ── PowerShell detection ──────────────────────────────────────────────────────


def _detect_pwsh() -> tuple[str, bool]:
    for exe in ("powershell", "pwsh"):
        try:
            subprocess.run(
                [exe, "-NoProfile", "-Command", "exit 0"],
                check=True,
                capture_output=True,
            )
            r = subprocess.run(
                [exe, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"],
                capture_output=True,
                text=True,
                check=True,
            )
            return exe, int(r.stdout.strip()) >= 7
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
            continue
    return None, False


_PWSH_EXE, _PWSH_V7 = _detect_pwsh()


# ── HTTP backends ─────────────────────────────────────────────────────────────


def _python_get(url: str) -> bytes:
    vlog_http("GET", url)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        vlog_http("GET", url, resp.status, len(body))
        return body


def _python_download(url: str, dest: Path) -> None:
    vlog_http("GET", url)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp:
        vlog_http("GET", url, resp.status)
        dest.write_bytes(b"".join(iter(lambda: resp.read(65536), b"")))


def _pwsh_run(script: str) -> subprocess.CompletedProcess:
    if not _PWSH_EXE:
        raise EnvironmentError("No PowerShell executable found.")
    result = subprocess.run(
        [_PWSH_EXE, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    vlog_pwsh(script, result.stdout, result.stderr, result.returncode)
    return result


def _ps_escape(s: str) -> str:
    return s.replace("'", "''")


def _pwsh_get(url: str) -> str:
    ari = " -AllowInsecureRedirect" if _PWSH_V7 else ""
    url_ps = _ps_escape(url)
    script = (
        "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'\n"
        f"$r = Invoke-WebRequest -Uri '{url_ps}' "
        f"-Headers @{{'User-Agent'='{_USER_AGENT}'}} -UseBasicParsing{ari}\n"
        "Write-Output $r.Content"
    )
    r = _pwsh_run(script)
    if r.returncode != 0:
        raise urllib.error.HTTPError(url, 0, (r.stdout + r.stderr).strip(), {}, None)
    return r.stdout


def _pwsh_download(url: str, dest: Path) -> None:
    ari = " -AllowInsecureRedirect" if _PWSH_V7 else ""
    url_ps = _ps_escape(url)
    dest_ps = _ps_escape(str(dest))
    script = (
        "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'\n"
        f"Invoke-WebRequest -Uri '{url_ps}' -OutFile '{dest_ps}' "
        f"-Headers @{{'User-Agent'='{_USER_AGENT}'}} -UseBasicParsing{ari}"
    )
    r = _pwsh_run(script)
    if r.returncode != 0:
        lines = [
            l.strip()
            for l in (r.stdout + r.stderr).splitlines()
            if l.strip() and "~~" not in l and "|" not in l
        ]
        raise RuntimeError(lines[-1] if lines else "PowerShell download failed")


# ── Unified HTTP API ──────────────────────────────────────────────────────────


def http_get(url: str, use_pwsh: bool = False) -> str:
    if use_pwsh:
        return _pwsh_get(url)
    return _python_get(url).decode("utf-8", errors="replace")


def http_download(url: str, dest: Path, use_pwsh: bool = False) -> None:
    if use_pwsh:
        _pwsh_download(url, dest)
    else:
        _python_download(url, dest)


# ── NuGet v2 OData ────────────────────────────────────────────────────────────

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
}


def _nuget_query(filter_expr: str, use_pwsh: bool = False) -> list[dict]:
    encoded = urllib.parse.quote(filter_expr, safe="()'")
    url = f"{_CHOCO_API}/Packages()?$filter={encoded}&semVerLevel=2.0.0"
    vlog(f"NuGet query: {url}")
    root = ET.fromstring(http_get(url, use_pwsh))
    results = []
    for entry in root.findall("atom:entry", _NS):
        props = entry.find("m:properties", _NS)
        if props is None:
            continue

        def p(name):
            el = props.find(f"d:{name}", _NS)
            return el.text if el is not None else ""

        title = entry.find("atom:title", _NS)
        content = entry.find("atom:content", _NS)
        pkg_id = title.text.strip() if title is not None and title.text else ""
        dl_url = content.get("src", "") if content is not None else ""
        version = p("Version")
        if not dl_url:
            dl_url = f"{_CHOCO_API}/package/{pkg_id}/{version}"
        results.append(
            {
                "id": pkg_id,
                "version": version,
                "download_url": dl_url,
                "is_latest": p("IsLatestVersion") in ("true", "True"),
                "dependencies": _parse_deps(p("Dependencies")),
            }
        )
    return results


def _parse_deps(dep_str: str) -> list[str]:
    """
    Parse Chocolatey NuGet v2 dependency string into resolve-able pkg specs.

    Wire format: 'id:versionSpec:targetFramework|id2:...'
      - versionSpec may be empty, a bare version, or a range like [1.0,2.0)
      - targetFramework token is ignored (may be an integer like '0')
    Returns 'id' or 'id@version' strings suitable for resolve_package().
    """
    if not dep_str or not dep_str.strip():
        return []
    specs = []
    for part in dep_str.split("|"):
        part = part.strip()
        if not part:
            continue
        segments = part.split(":")
        dep_id = segments[0].strip()
        # Package ids must start with a letter; pure-integer tokens are framework monikers
        if not dep_id or not re.match(r"^[A-Za-z]", dep_id):
            continue
        dep_ver = segments[1].strip() if len(segments) > 1 else ""
        # Strip NuGet range notation: [1.0,2.0) → take lower bound "1.0"
        dep_ver = re.sub(r"^[\[(]", "", dep_ver)  # remove leading [ or (
        dep_ver = re.sub(r"[\])].*$", "", dep_ver)  # remove from ] or ) onward
        dep_ver = dep_ver.split(",")[0].strip()  # take lower bound if range remains
        dep_ver = re.sub(r"^[<>=!\s]+", "", dep_ver).strip()
        specs.append(f"{dep_id}@{dep_ver}" if dep_ver else dep_id)
    return specs


def resolve_package(pkg_spec: str, use_pwsh: bool = False) -> dict:
    """Resolve 'name' or 'name@version' → metadata dict."""
    if "@" in pkg_spec:
        name, version = pkg_spec.split("@", 1)
        filt = f"(tolower(Id) eq '{name.lower()}') and Version eq '{version}'"
    else:
        name = pkg_spec
        filt = f"(tolower(Id) eq '{name.lower()}') and IsLatestVersion"
    results = _nuget_query(filt, use_pwsh)
    if not results:
        raise ValueError(f"Package not found on Chocolatey: {pkg_spec!r}")
    return results[0]


def download_nupkg(
    meta: dict,
    dest_dir: Path,
    use_pwsh: bool = False,
    quiet: bool = False,
    force: bool = False,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{meta['id']}.{meta['version']}.nupkg"
    dest = dest_dir / filename
    if dest.exists() and not force:
        if not quiet:
            print(f"  {SKIP} {dim('exists:')} {dim(str(dest))}")
        return dest
    if not quiet:
        print(f"  {DL} {cpkg(filename)}")
    with Spinner(f"Fetching {filename}"):
        http_download(meta["download_url"], dest, use_pwsh)
    if not quiet:
        sz = dest.stat().st_size
        size_str = f"{sz / 1_048_576:.1f} MB" if sz >= 1_048_576 else f"{sz // 1024} KB"
        print(f"  {CHECK} {ok(filename)}  {dim(size_str)}")
    return dest


def resolve_with_deps(
    pkg_spec: str,
    use_pwsh: bool = False,
    _seen: "set | None" = None,
    _depth: int = 0,
) -> list[dict]:
    """
    Recursively resolve pkg_spec and all transitive dependencies.

    Returns metadata dicts in dependency-first order (leaves first), no
    duplicates.  Each dict carries 'dep_depth' for display indentation.
    """
    if _seen is None:
        _seen = set()
    bare_id = pkg_spec.split("@")[0].lower()
    if bare_id in _seen:
        return []
    _seen.add(bare_id)

    try:
        meta = resolve_package(pkg_spec, use_pwsh)
    except ValueError as e:
        print(f"  {CROSS} {err(pkg_spec)}: {e}")
        return []

    meta["dep_depth"] = _depth
    results = []
    for dep_spec in meta.get("dependencies", []):
        results.extend(resolve_with_deps(dep_spec, use_pwsh, _seen, _depth + 1))
    results.append(meta)
    return results


def resolve_and_download_packages(
    pkg_specs: list[str],
    dest_dir: Path,
    use_pwsh: bool = False,
    quiet: bool = False,
    force: bool = False,
    include_deps: bool = False,
) -> list[Path]:
    all_meta: list[dict] = []
    seen_ids: set[str] = set()

    for spec in pkg_specs:
        if include_deps:
            resolved = resolve_with_deps(spec, use_pwsh)
        else:
            try:
                resolved = [resolve_package(spec, use_pwsh)]
            except (ValueError, RuntimeError) as e:
                print(f"  {CROSS} {err(spec)}: {e}")
                continue

        for meta in resolved:
            if meta["id"].lower() not in seen_ids:
                seen_ids.add(meta["id"].lower())
                all_meta.append(meta)

    nupkgs = []
    for meta in all_meta:
        depth = meta.get("dep_depth", 0)
        indent = "  " + ("  " * depth)
        label = dim("(dep) ") if depth > 0 else ""
        if not quiet:
            print(f"{indent}{label}{cpkg(meta['id'])} {dim(meta['version'])}")
        try:
            nupkgs.append(download_nupkg(meta, dest_dir, use_pwsh, quiet, force))
        except (RuntimeError, OSError) as e:
            print(f"{indent}{CROSS} {err(meta['id'])}: {e}")

    return nupkgs
