# CHOMP

**Chocolatey Handler for Offline Package Mirroring & Processing**

Internalize or rewrite Chocolatey `.nupkg` packages for air-gapped deployments.
Mirrors `choco download --internalize` without requiring the Chocolatey CLI or any third-party Python dependencies.

```bash
pip install chomp
```

Requires Python 3.11+.

---

## Modes

### `internalize` (alias: `seal`)

Embeds installer binaries **inside** the `.nupkg` under `tools/files/`. Scripts reference them locally:

```powershell
$(Split-Path -parent $MyInvocation.MyCommand.Definition)\files\setup.exe
```

Result: a fully self-contained `.nupkg` for offline NuGet feeds.

### `rewrite` (alias: `repack`)

Rewrites installer URLs in `.ps1` scripts to point at an internal server. Installers are staged separately under `installers/<package>/<version>/`. Requires `--base-url`.

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

# Force re-download and overwrite existing .nupkg and installers
chomp internalize googlechrome --force

# Use PowerShell HTTP backend (corporate proxy environments)
chomp internalize googlechrome --pwsh

# Interactive URL confirmation before downloads
chomp internalize --packages-dir ./pkgs --interactive

# Dry run — show what would happen, write nothing
chomp internalize googlechrome --dry-run

# Verbose debug output
chomp internalize googlechrome --verbose
```

---

## Flags

| Flag                  | Description                                                            |
| --------------------- | ---------------------------------------------------------------------- |
| `mode`                | `internalize` / `seal` or `rewrite` / `repack` (required)              |
| `PACKAGE[@VER]`       | Packages to fetch from Chocolatey                                      |
| `-p / --packages-dir` | Local `.nupkg` directory to process                                    |
| `-o / --out-dir`      | Output directory (default: `chomp/out/<mode>/`)                        |
| `-i / --installers`   | Installer staging directory (default: `chomp/installers/`)             |
| `--fetch-dir`         | Cache for downloaded `.nupkg` files (default: `chomp/nupkgs/`)         |
| `--in-place`          | Write output back into `--packages-dir`                                |
| `-u / --base-url`     | Internal package base URL (required for `rewrite`)                     |
| `--pwsh`              | Use PowerShell (`Invoke-WebRequest`) for HTTP                          |
| `--skip-download`     | Rewrite scripts only; skip installer downloads                         |
| `--interactive`       | Confirm each URL before downloading                                    |
| `--force`             | Re-download and overwrite existing `.nupkg` and installer files        |
| `--manifest`          | CSV audit log path (default: `chomp/manifests/<mode>_<timestamp>.csv`) |
| `--manifest-json`     | Also write a JSON audit log to this path                               |
| `--dry-run`           | Print actions without writing any files                                |
| `-q / --quiet`        | Suppress progress output                                               |
| `-v / --verbose`      | Print debug information                                                |

Environment variable `CHOMP_REPO` overrides the repo root (default: `./chomp`).

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

## Output structure

**internalize:**

```
out/internalized/
  googlechrome.126.0.nupkg   ← self-contained; installers embedded inside
installers/
  googlechrome/126.0/
    googlechromestandaloneenterprise64.msi
manifests/
  internalize_20260521_120000.csv
```

Inside the `.nupkg`, `tools/` looks like:

```
tools/
  chocolateyInstall.ps1      ← URLs replaced with local \files\ references
  files/
    googlechromestandaloneenterprise64.msi
```

**rewrite:**

```
out/rewritten/
  googlechrome.126.0.nupkg   ← URLs rewritten to internal server
installers/
  googlechrome/126.0/
    googlechromestandaloneenterprise64.msi
manifests/
  rewrite_20260521_120000.csv
```

---

## Error handling

CHOMP distinguishes three error classes:

**Per-package / per-download failures** — logged inline with `✗` and included in the summary and manifest. The run continues with remaining packages.

**Fatal errors** (bad args, missing mode, unreadable directory) — printed as a clean one-liner to stderr and exit code 1:

```
error: rewrite mode requires --base-url
```

**Interrupted runs** (`Ctrl-C`) — prints a clean abort line and any partial progress before exiting with code 130:

```
interrupted (ctrl-c)
  3 installer(s) downloaded before interrupt
```

### Tracebacks

By default, tracebacks are suppressed for clean output. Enable them two ways:

```bash
# via flag (also enables verbose debug output)
chomp internalize googlechrome -v

# via environment variable (traceback only, no extra verbosity)
CHOMP_TRACEBACK=1 chomp internalize googlechrome
```

Exit codes: `0` success, `1` error, `2` bad arguments, `130` interrupted.

---



CHOMP skips URLs that aren't downloadable installer paths:

- PowerShell variable references (`$var`)
- Template placeholders (`<tag>`, `{...}`)
- Truncated or malformed URLs
- URLs without a recognisable installer extension
- Missing or localhost hostnames

Use `--interactive` to manually approve or edit each URL before download.

---

## Python API

```python
from chomp import (
    resolve_and_download_packages,
    process_nupkg_phase1,
    download_batch,
    installer_path,
    finalize_nupkg,
    write_csv,
)
from pathlib import Path
import tempfile

nupkgs = resolve_and_download_packages(["googlechrome", "7zip@24.9"], Path("nupkgs"))

all_mappings = []
out_dir = Path("out/internalized")

with tempfile.TemporaryDirectory() as tmp:
    for nupkg in nupkgs:
        mappings = process_nupkg_phase1(
            nupkg=nupkg,
            base_url=None,
            out_dir=out_dir,
            work_dir=Path(tmp),
            mode="internalize",
        )
        if mappings:
            all_mappings.extend(mappings)

installer_dir = Path("installers")
all_mappings = download_batch(all_mappings, installer_dir)

def resolve(m): return installer_path(m, installer_dir)

with tempfile.TemporaryDirectory() as tmp2:
    for nupkg in out_dir.glob("*.nupkg"):
        pkg_id   = nupkg.stem.split(".")[0]
        pkg_maps = [m for m in all_mappings if m["package"] == pkg_id]
        if pkg_maps:
            finalize_nupkg(nupkg, pkg_maps, resolve, out_dir, Path(tmp2), "internalize")

write_csv(all_mappings, Path("manifests/audit.csv"))
```

> **Note:** `process_nupkg_phase1` returns `None` if the output `.nupkg` already exists and `force=False`. Check for `None` before extending `all_mappings`.
