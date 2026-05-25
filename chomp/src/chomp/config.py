"""chomp.config — Single source of truth for paths, modes, and CLI help."""

import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

# ── Repo layout ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RepoLayout:
    nupkgs: str = "nupkgs"
    installers: str = "installers"
    out_internalized: str = "out/internalized"
    out_rewritten: str = "out/rewritten"
    manifests: str = "manifests"


REPO_LAYOUT = RepoLayout()

# Map canonical mode names to the RepoLayout field that holds their out path.
_MODE_OUT_FIELD = {
    "internalize": "out_internalized",
    "rewrite": "out_rewritten",
}


# ── Mode system ───────────────────────────────────────────────────────────────

MODE_ALIASES = {"seal": "internalize", "repack": "rewrite"}
VALID_MODES = frozenset(_MODE_OUT_FIELD)


def normalize_mode(mode: str) -> str:
    return MODE_ALIASES.get(mode, mode)


def validate_mode(mode: str) -> str:
    mode = normalize_mode(mode)
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode!r}")
    return mode


# ── Path helpers ──────────────────────────────────────────────────────────────


def get_repo_root() -> Path:
    return Path(os.environ.get("CHOMP_REPO", "./chomp.out")).resolve()


def repo_path(root: Path, key: str) -> Path:
    """Resolve a RepoLayout field name to an absolute path under root."""
    return root / getattr(REPO_LAYOUT, key)


def get_out_dir(root: Path, mode: str) -> Path:
    field = _MODE_OUT_FIELD[validate_mode(mode)]
    return repo_path(root, field)


def get_manifest_path(root: Path, mode: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return repo_path(root, "manifests") / f"{validate_mode(mode)}_{ts}.csv"


# ── Repo structure ────────────────────────────────────────────────────────────


def ensure_repo_structure(root: Path) -> None:
    """Create the full repo skeleton from REPO_LAYOUT — no hardcoded paths."""
    for f in fields(REPO_LAYOUT):
        (root / getattr(REPO_LAYOUT, f.name)).mkdir(parents=True, exist_ok=True)


# ── CLI help text ─────────────────────────────────────────────────────────────

CLI_HELP = {
    "mode": "internalize/seal — embed installers inside nupkg. rewrite/repack — rewrite URLs to internal server.",
    "packages": "Package names to fetch from Chocolatey (e.g. googlechrome 7zip@24.9).",
    "packages_dir": "Directory containing existing .nupkg files to process.",
    "out_dir": f"Output directory (default: $CHOMP_REPO/{REPO_LAYOUT.out_internalized} or …/{REPO_LAYOUT.out_rewritten}).",
    "installers": f"Installer staging directory (default: $CHOMP_REPO/{REPO_LAYOUT.installers}/).",
    "fetch_dir": f"Cache directory for downloaded .nupkg files (default: $CHOMP_REPO/{REPO_LAYOUT.nupkgs}/).",
    "in_place": "Write output back into --packages-dir instead of out/.",
    "base_url": "[rewrite] Internal server base URL (e.g. http://repo.local/packages).",
    "pwsh": "Use PowerShell (Invoke-WebRequest) for HTTP — useful in corporate proxy environments.",
    "skip_download": "Skip installer downloads; rewrite scripts only.",
    "interactive": "Confirm each installer URL before downloading.",
    "force": "Re-download and overwrite existing .nupkg and installer files.",
    "manifest": f"CSV audit log path (default: $CHOMP_REPO/{REPO_LAYOUT.manifests}/<mode>_<timestamp>.csv).",
    "manifest_json": "Also write a JSON audit log to this path.",
    "deps": "Resolve and process transitive Chocolatey dependencies.",
    "dry_run": "Print planned actions without writing any files.",
    "quiet": "Suppress progress output.",
    "verbose": "Print debug information.",
}
