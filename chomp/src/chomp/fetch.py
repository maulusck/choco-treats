"""
fetch.py — HTTP + Chocolatey NuGet v2 resolver/downloader.

The HTTP transport is a swappable backend selected once via configure():
  RequestsBackend   (default) — shared requests.Session.
  PowerShellBackend (--pwsh)  — shells out to system PowerShell for proxies.
Both honour the rate limiter; the resolver code never sees which is active.
"""

import re
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from .config import DEFAULT_CHOCO_REPO, DEFAULT_RATE_LIMIT
from .term import CHECK, CROSS, DL, SKIP, console, dim, err, ok
from .term import pkg as cpkg
from .term import spinner, vlog, vlog_http, warn

_USER_AGENT = "NuGet/6.0 (Microsoft Windows NT 10.0; chomp)"


def _filename_from_response(r: "requests.Response") -> str | None:
    """Best server-suggested filename: Content-Disposition, else final URL basename."""
    cd = r.headers.get("Content-Disposition", "") or ""
    m = re.search(r"filename\*?=(?:[^']*'')?\"?([^\";]+)\"?", cd)
    if m:
        return urllib.parse.unquote(m.group(1).strip().strip('"')) or None
    name = Path(urllib.parse.urlparse(r.url).path).name
    return urllib.parse.unquote(name) if name else None


# ── Rate limiting ─────────────────────────────────────────────────────────────


class _RateLimiter:
    """Enforce a minimum interval between requests (thread-safe)."""

    def __init__(self, rps: float):
        self.min_interval = 1.0 / rps if rps and rps > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        if not self.min_interval:
            return
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


# ── Downloader backends ───────────────────────────────────────────────────────
# A backend is any object exposing `get(url) -> str` and `download(url, dest)`.
# Selecting one is the only thing that varies between HTTP transports, so the
# resolver/downloader code below never needs to know which is active.


class RequestsBackend:
    """Default transport: a shared requests.Session (honours *_PROXY env vars)."""

    def __init__(self, verify: bool, limiter: _RateLimiter):
        self.verify, self.limiter = verify, limiter
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _USER_AGENT
        if not verify:
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    def _request(self, url: str, **kw) -> requests.Response:
        for attempt in range(4):  # exponential backoff on HTTP 429
            self.limiter.wait()
            vlog_http("GET", url)
            r = self.session.get(url, verify=self.verify, **kw)
            if r.status_code == 429 and attempt < 3:
                delay = float(r.headers.get("Retry-After", 2**attempt))
                vlog(f"429 from server — backing off {delay:.0f}s")
                time.sleep(delay)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"Rate-limited (HTTP 429) after retries: {url}")

    def get(self, url: str) -> str:
        r = self._request(url, timeout=60)
        vlog_http("GET", url, r.status_code, len(r.content))
        return r.text

    def download(self, url: str, dest: Path) -> str | None:
        with self._request(url, timeout=300, stream=True) as r, open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
            return _filename_from_response(r)


class PowerShellBackend:
    """
    Transport that shells out to a system PowerShell (`pwsh` or `powershell`)
    and drives Invoke-WebRequest. Useful behind aggressive corporate proxies
    where the OS credential / proxy store must be used (NTLM, Kerberos, MITM).
    Fully self-contained: no dependency on the requests path.
    """

    def __init__(self, verify: bool, limiter: _RateLimiter):
        self.verify, self.limiter = verify, limiter
        self.exe, self.is_v7 = self._detect()
        if not self.exe:
            raise EnvironmentError("No PowerShell executable found (pwsh/powershell).")
        vlog(f"PowerShell backend: {self.exe} (v7+={self.is_v7})")

    @staticmethod
    def _detect() -> tuple:
        for exe in ("pwsh", "powershell"):
            try:
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

    @staticmethod
    def _esc(s: str) -> str:
        return s.replace("'", "''")

    def _flags(self) -> str:
        f = " -UseBasicParsing"
        if self.is_v7:
            f += " -AllowInsecureRedirect"
            if not self.verify:
                f += " -SkipCertificateCheck"
        return f

    def _run(self, body: str) -> subprocess.CompletedProcess:
        script = "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'\n" + body
        r = subprocess.run(
            [self.exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
        )
        vlog(f"pwsh exit={r.returncode}")
        return r

    def _fail(self, r) -> str:
        lines = [
            ln.strip()
            for ln in (r.stdout + r.stderr).splitlines()
            if ln.strip() and "~~" not in ln and "|" not in ln
        ]
        return lines[-1] if lines else "PowerShell request failed"

    def get(self, url: str) -> str:
        self.limiter.wait()
        vlog_http("GET", url)
        r = self._run(
            f"$r = Invoke-WebRequest -Uri '{self._esc(url)}' "
            f"-Headers @{{'User-Agent'='{_USER_AGENT}'}}{self._flags()}\n"
            "Write-Output $r.Content"
        )
        if r.returncode != 0:
            raise RuntimeError(self._fail(r))
        return r.stdout

    def download(self, url: str, dest: Path) -> None:
        self.limiter.wait()
        vlog_http("GET", url)
        r = self._run(
            f"Invoke-WebRequest -Uri '{self._esc(url)}' -OutFile '{self._esc(str(dest))}' "
            f"-Headers @{{'User-Agent'='{_USER_AGENT}'}}{self._flags()}"
        )
        if r.returncode != 0:
            raise RuntimeError(self._fail(r))


# ── Runtime config ────────────────────────────────────────────────────────────

_CHOCO_API = DEFAULT_CHOCO_REPO
_backend = RequestsBackend(verify=True, limiter=_RateLimiter(DEFAULT_RATE_LIMIT))


def configure(
    repo_url: str = None,
    rate: float = DEFAULT_RATE_LIMIT,
    insecure: bool = False,
    use_pwsh: bool = False,
):
    global _CHOCO_API, _backend
    if repo_url:
        _CHOCO_API = repo_url.rstrip("/")
    limiter = _RateLimiter(rate)
    backend_cls = PowerShellBackend if use_pwsh else RequestsBackend
    _backend = backend_cls(verify=not insecure, limiter=limiter)


# ── Unified HTTP API (delegates to the active backend) ────────────────────────


def http_get(url: str) -> str:
    return _backend.get(url)


def http_download(url: str, dest: Path) -> str | None:
    return _backend.download(url, dest)


# ── NuGet v2 OData ────────────────────────────────────────────────────────────

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
}


def _nuget_query(filter_expr: str) -> list[dict]:
    encoded = urllib.parse.quote(filter_expr, safe="()'")
    url = f"{_CHOCO_API}/Packages()?$filter={encoded}&semVerLevel=2.0.0"
    vlog(f"NuGet query: {url}")
    root = ET.fromstring(http_get(url))
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
        version = p("Version")
        dl_url = content.get("src", "") if content is not None else ""
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
    Parse a NuGet v2 dependency string into 'id' / 'id@version' specs.

    Wire format: 'id:versionSpec:targetFramework|id2:...'. The version spec may
    be empty, a bare version, or a range like [1.0,2.0); we take its lower bound.
    Pure-integer tokens are framework monikers and are skipped.
    """
    specs = []
    for part in (dep_str or "").split("|"):
        segments = part.strip().split(":")
        dep_id = segments[0].strip()
        if not dep_id or not re.match(r"^[A-Za-z]", dep_id):
            continue
        ver = segments[1].strip() if len(segments) > 1 else ""
        ver = re.sub(r"^[\[(]", "", ver)  # drop leading [ or (
        ver = re.sub(r"[\])].*$", "", ver)  # drop from ] or ) onward
        ver = re.sub(r"^[<>=!\s]+", "", ver.split(",")[0]).strip()
        specs.append(f"{dep_id}@{ver}" if ver else dep_id)
    return specs


def resolve_package(pkg_spec: str) -> dict:
    """Resolve 'name' or 'name@version' → metadata dict."""
    if "@" in pkg_spec:
        name, version = pkg_spec.split("@", 1)
        filt = f"(tolower(Id) eq '{name.lower()}') and Version eq '{version}'"
    else:
        filt = f"(tolower(Id) eq '{pkg_spec.lower()}') and IsLatestVersion"
    results = _nuget_query(filt)
    if not results:
        raise ValueError(f"Package not found: {pkg_spec!r}")
    return results[0]


def download_nupkg(meta: dict, dest_dir: Path, quiet: bool = False, force: bool = False) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{meta['id']}.{meta['version']}.nupkg"
    dest = dest_dir / filename
    if dest.exists() and not force:
        if not quiet:
            console.print(f"  {SKIP} {dim('exists:')} {dim(str(dest))}")
        return dest
    if not quiet:
        console.print(f"  {DL} {cpkg(filename)}")
    with spinner(f"Fetching {filename}"):
        http_download(meta["download_url"], dest)
    if not quiet:
        sz = dest.stat().st_size
        size = f"{sz / 1_048_576:.1f} MB" if sz >= 1_048_576 else f"{sz // 1024} KB"
        console.print(f"  {CHECK} {ok(filename)}  {dim(size)}")
    return dest


def resolve_with_deps(pkg_spec: str, _seen=None, _depth=0) -> list[dict]:
    """Recursively resolve pkg_spec + transitive deps, leaves first, no dupes."""
    _seen = set() if _seen is None else _seen
    bare_id = pkg_spec.split("@")[0].lower()
    if bare_id in _seen:
        return []
    _seen.add(bare_id)
    try:
        meta = resolve_package(pkg_spec)
    except ValueError as e:
        console.print(f"  {CROSS} {err(pkg_spec)}: {dim(e)}")
        return []
    meta["dep_depth"] = _depth
    results = []
    for dep in meta.get("dependencies", []):
        results.extend(resolve_with_deps(dep, _seen, _depth + 1))
    results.append(meta)
    return results


def resolve_and_download_packages(
    pkg_specs: list[str],
    dest_dir: Path,
    quiet: bool = False,
    force: bool = False,
    include_deps: bool = False,
) -> list[Path]:
    all_meta, seen_ids = [], set()
    for spec in pkg_specs:
        if include_deps:
            resolved = resolve_with_deps(spec)
        else:
            try:
                resolved = [resolve_package(spec)]
            except (ValueError, RuntimeError) as e:
                console.print(f"  {CROSS} {err(spec)}: {dim(e)}")
                continue
        for meta in resolved:
            if meta["id"].lower() not in seen_ids:
                seen_ids.add(meta["id"].lower())
                all_meta.append(meta)

    nupkgs = []
    for meta in all_meta:
        depth = meta.get("dep_depth", 0)
        indent = "  " + ("  " * depth)
        if not quiet:
            label = dim("(dep) ") if depth else ""
            console.print(f"{indent}{label}{cpkg(meta['id'])} {dim(meta['version'])}")
        try:
            nupkgs.append(download_nupkg(meta, dest_dir, quiet, force))
        except (RuntimeError, OSError, requests.RequestException) as e:
            console.print(f"{indent}{CROSS} {err(meta['id'])}: {dim(e)}")
    return nupkgs
