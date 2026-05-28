# CHOMP

**Chocolatey Handler for Offline [package] Mirroring & Processing**

Internalize or rewrite Chocolatey `.nupkg` packages for air-gapped deployments.
Mirrors `choco download --internalize` without requiring the Chocolatey CLI.

```bash
pip install chomp          # core (uses requests)
pip install chomp[color]   # + rich colored output (optional)
```

Requires Python 3.11+. Depends on `requests`; `rich` is optional — without it,
output falls back to monochrome and a one-line install hint is printed.

---

## Modes

The two modes share one pipeline (scan → download → build) and differ only in
how the installer reference is written and whether the installer is embedded.

### `internalize` (alias: `seal`)

Embeds installer binaries **inside** the `.nupkg` under `tools/files/`. Scripts
reference them locally:

```powershell
$(Split-Path -parent $MyInvocation.MyCommand.Definition)\files\setup.exe
```

Result: a fully self-contained `.nupkg` for offline NuGet feeds.

### `rewrite` (alias: `repack`)

Rewrites installer URLs in `.ps1` scripts to point at an internal server.
Installers are staged separately under `installers/<package>/<version>/`.
Requires `--base-url`.

In both modes, embedded `-Checksum` values are re-patched to the SHA-256 of the
downloaded file.

---

## Usage

```bash
# Internalize packages fetched from Chocolatey
chomp internalize googlechrome 7zip

# Pin a version
chomp internalize googlechrome@126.0 7zip@24.9

# Process a local .nupkg directory
chomp internalize --packages-dir ./pkgs

# Rewrite mode with internal repo
chomp rewrite --base-url http://repo.local/packages googlechrome

# Resolve transitive dependencies
chomp internalize firefox --deps

# Use a different NuGet v2 source
chomp internalize 7zip --source https://my.feed/api/v2

# Throttle / disable API rate limiting (avoids HTTP 429)
chomp internalize 7zip --rate-limit 5      # 5 req/sec
chomp internalize 7zip --rate-limit 0      # unlimited

# Skip TLS verification (e.g. internal MITM proxy)
chomp internalize 7zip --insecure

# Route HTTP through system PowerShell (NTLM/Kerberos corporate proxies)
chomp internalize 7zip --pwsh

# Force, interactive, dry run, verbose
chomp internalize googlechrome --force
chomp internalize --packages-dir ./pkgs --interactive
chomp internalize googlechrome --dry-run
chomp internalize googlechrome --verbose
```

> Corporate proxies: `requests` honours the standard `HTTP_PROXY` /
> `HTTPS_PROXY` / `NO_PROXY` environment variables automatically. For proxies
> that require OS-integrated auth (NTLM/Kerberos), use `--pwsh`, which delegates
> HTTP to a system PowerShell (`pwsh` or `powershell`).

---

## Flags

| Flag                  | Description                                                            |
| --------------------- | ---------------------------------------------------------------------- |
| `mode`                | `internalize` / `seal` or `rewrite` / `repack` (required)              |
| `PACKAGE[@VER]`       | Packages to fetch from Chocolatey                                      |
| `-p / --packages-dir` | Local `.nupkg` directory to process                                    |
| `-o / --out-dir`      | Output directory (default: `$CHOMP_REPO/out/<mode>/`)                  |
| `-i / --installers`   | Installer staging directory (default: `$CHOMP_REPO/installers/`)       |
| `--fetch-dir`         | Cache for downloaded `.nupkg` files (default: `$CHOMP_REPO/nupkgs/`)   |
| `--in-place`          | Write output back into `--packages-dir`                                |
| `-u / --base-url`     | Internal package base URL (required for `rewrite`)                     |
| `-s / --source`       | Chocolatey NuGet v2 repo URL (default: community feed)                 |
| `-k / --insecure`     | Skip TLS certificate verification                                      |
| `--pwsh`              | Use a system PowerShell backend for HTTP (aggressive corporate proxies) |
| `--rate-limit RPS`    | Max API requests/sec; `0` disables limiting (default: `10`)            |
| `--deps`              | Resolve and process transitive dependencies                           |
| `--skip-download`     | Rewrite scripts only; skip installer downloads                         |
| `--interactive`       | Confirm each URL before downloading                                    |
| `--force`             | Re-download and overwrite existing `.nupkg` and installer files        |
| `--manifest`          | CSV audit log path (default: `$CHOMP_REPO/manifests/<mode>_<ts>.csv`)  |
| `--manifest-json`     | Also write a JSON audit log to this path                               |
| `--dry-run`           | Print actions without writing any files                                |
| `-q / --quiet`        | Suppress progress output                                               |
| `-v / --verbose`      | Print debug information                                                |

Environment variable `CHOMP_REPO` overrides the repo root (default: `./chomp.out`).

---

## Repository layout (auto-created)

```
chomp.out/
  nupkgs/          ← downloaded .nupkg cache
  installers/      ← staged installer binaries
  out/
    internalized/  ← internalize mode output
    rewritten/     ← rewrite mode output
  manifests/       ← CSV / JSON audit logs
```

---

## Error handling

- **Per-package / per-download failures** — logged inline with `✗`, included in
  the summary and manifest; the run continues.
- **HTTP 429** — automatically retried with exponential backoff; tune throughput
  with `--rate-limit`.
- **Fatal errors** (bad args, missing mode) — clean one-liner to stderr, exit 1.
- **Interrupts** (`Ctrl-C`) — clean abort line plus partial progress, exit 130.

Tracebacks are suppressed by default; enable with `-v` or `CHOMP_TRACEBACK=1`.
Exit codes: `0` success, `1` error, `2` bad arguments, `130` interrupted.

URLs that aren't downloadable installer paths are skipped (PowerShell variables,
template placeholders, truncated URLs, unknown extensions, missing/localhost
hosts). Use `--interactive` to approve or edit each URL.

---

## Python API

```python
import tempfile
from pathlib import Path
from chomp import (
    configure, resolve_and_download_packages, collect_urls,
    download_batch, installer_path, build_nupkg, write_csv,
)

configure(rate=10)                       # optional: source/rate/insecure
out_dir = Path("out/internalized")
installer_dir = Path("installers")

nupkgs = resolve_and_download_packages(["googlechrome", "7zip@24.9"], Path("nupkgs"))

# Phase 1 — scan (returns None if already built and force=False)
per_pkg = {n: m for n in nupkgs
           if (m := collect_urls(n, base_url=None, out_dir=out_dir,
                                 mode="internalize", force=False)) is not None}
all_maps = [m for maps in per_pkg.values() for m in maps]

# Phase 2 — download installers
all_maps = download_batch(all_maps, installer_dir)

# Phase 3 — build
resolve = lambda m: installer_path(m, installer_dir)
with tempfile.TemporaryDirectory() as tmp:
    for nupkg, maps in per_pkg.items():
        build_nupkg(nupkg, maps, resolve, out_dir, Path(tmp), "internalize")

write_csv(all_maps, Path("manifests/audit.csv"))
```
