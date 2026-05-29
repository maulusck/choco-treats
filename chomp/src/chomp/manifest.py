"""manifest.py — Write/read the audit trail (CSV + JSON) and render run reports."""

import csv
import json
from collections import OrderedDict
from pathlib import Path

from .config import now_iso
from .term import bold, console, dim, err, info, ok
from .term import pkg as cpkg
from .term import rule, url_old, warn

# Per-operation columns. run_id + timestamps lead so the CSV is self-describing.
FIELDS = [
    "run_id",
    "scanned_at",
    "downloaded_at",
    "package",
    "version",
    "ps1",
    "mode",
    "old_url",
    "new_url",
    "filename",
    "downloaded",
    "skip_reason",
    "checksum_patched",
    "new_checksum",
]

# downloaded-status → (human label, glyph-color fn). Single source for summary + report.
_STATUS = OrderedDict(
    [
        ("ok", "downloaded"),
        ("skipped-exists", "already present"),
        ("skipped-duplicate", "duplicate"),
        ("skipped-filtered", "filtered (no file URL)"),
        ("skipped-interactive", "skipped (user)"),
        ("failed", "failed"),
    ]
)
_ATTENTION = ("failed", "skipped-filtered")  # the statuses that need a human


# ── Summary ────────────────────────────────────────────────────────────────


def summarize(ops: list[dict]) -> dict:
    def c(status):
        return sum(1 for m in ops if m.get("downloaded") == status)

    return {
        "urls_found": len(ops),
        "downloaded": c("ok"),
        "exists": c("skipped-exists"),
        "duplicates": c("skipped-duplicate"),
        "filtered": c("skipped-filtered"),
        "failed": c("failed"),
        "checksums_patched": sum(1 for m in ops if _truthy(m.get("checksum_patched"))),
    }


def _truthy(v) -> bool:
    # Real bools from JSON, or "yes"/"" round-tripped through CSV.
    return v is True or (isinstance(v, str) and v.strip().lower() in ("yes", "true", "1"))


# ── Writers ──────────────────────────────────────────────────────────────────


def write_csv(ops: list[dict], path: Path, run_id: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for op in ops:
            row = dict(op)
            row.setdefault("run_id", run_id)
            # Coerce bool so it re-reads cleanly ("False" would be truthy as a string).
            row["checksum_patched"] = "yes" if _truthy(op.get("checksum_patched")) else ""
            w.writerow(row)


def write_json(run: dict, ops: list[dict], path: Path, summary: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"run": run, "summary": summary or summarize(ops), "operations": ops}
    path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")


# ── Reader ─────────────────────────────────────────────────────────────────


def load_manifest(path) -> dict:
    """Load a JSON manifest (full), or a CSV (operations only) → unified dict."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    with open(path, newline="", encoding="utf-8") as f:
        ops = list(csv.DictReader(f))
    run = {"run_id": ops[0].get("run_id", "") if ops else "", "source_file": str(path)}
    return {"run": run, "summary": summarize(ops), "operations": ops}


# ── Terminal summary (live run) ──────────────────────────────────────────────


def print_summary(mappings: list[dict]) -> None:
    s = summarize(mappings)
    rows = [
        ("URLs found", s["urls_found"], None),
        ("Downloaded", s["downloaded"], ok),
        ("Already exist", s["exists"], None),
        ("Duplicates skipped", s["duplicates"], None),
        ("Filtered (no-file)", s["filtered"], warn),
        ("Failed", s["failed"], err),
        ("Checksums patched", s["checksums_patched"], ok),
    ]
    bar = rule()
    console.print(f"\n{bar}\n  {bold('Summary')}\n{bar}")
    for label, value, color in rows:
        val = color(str(value)) if color and value else dim(str(value))
        console.print(f"  {dim(f'{label:<26}')} {val}")
    console.print(bar)


# ── Report ("explain") ───────────────────────────────────────────────────────


def explain(path) -> None:
    """Render a saved manifest as a human-readable run report."""
    data = load_manifest(path)
    run = data.get("run", {})
    ops = data.get("operations", [])
    summary = data.get("summary") or summarize(ops)

    bar = rule()
    console.print(f"\n{bar}\n  {bold('chomp run report')}  {dim(run.get('run_id', '?'))}\n{bar}")
    _header(run)

    # ── Per-package status ──
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for op in ops:
        groups.setdefault((op.get("package", "?"), op.get("version", "")), []).append(op)

    console.print(f"\n  {bold('Packages')} {dim(f'({len(groups)})')}")
    for (name, ver), items in groups.items():
        console.print(f"    {cpkg(f'{name} {ver}'.strip())}  {_pkg_note(items)}")

    # ── Needs attention ──
    flagged = [o for o in ops if o.get("downloaded") in _ATTENTION]
    if flagged:
        console.print(f"\n  {err('Needs attention')} {dim(f'({len(flagged)})')}")
        for o in flagged:
            reason = o.get("skip_reason") or _STATUS.get(o.get("downloaded"), "")
            console.print(f"    {err('✗')} {dim(f'[{reason}]')}")
            console.print(f"      {url_old(o.get('old_url', ''))}")
            console.print(f"      {info('→')} {_remediation(o)}")

    # ── Counts ──
    console.print(
        f"\n  {dim('totals:')} {summary['urls_found']} urls · "
        f"{ok(str(summary['downloaded']))} done · "
        f"{summary['exists']} existing · "
        f"{warn(str(summary['filtered']))} filtered · "
        f"{err(str(summary['failed']))} failed · "
        f"{summary['checksums_patched']} checksums"
    )
    console.print(bar)


def _header(run: dict) -> None:
    def line(label, value):
        if value not in (None, "", []):
            console.print(dim(f"  {label:<11}: ") + dim(str(value)))

    mode = run.get("mode", "")
    alias = run.get("mode_input")
    line("mode", f"{mode} ({alias})" if alias and alias != mode else mode)
    line("started", run.get("started_at"))
    fin = run.get("finished_at")
    if fin:
        line("finished", f"{fin}  {_duration(run)}".strip())
    line("source", run.get("source"))
    line("base url", run.get("base_url"))
    line("chomp", run.get("chomp_version"))
    flags = [k for k, v in (run.get("flags") or {}).items() if v]
    line("flags", ", ".join(flags) or "—")
    req = run.get("packages_requested") or []
    line("requested", ", ".join(req) or "(swept from packages dir)")
    if run.get("dry_run"):
        console.print(f"  {warn('(dry run — nothing was written)')}")


def _duration(run: dict) -> str:
    from datetime import datetime as _dt

    try:
        d = _dt.fromisoformat(run["finished_at"]) - _dt.fromisoformat(run["started_at"])
        return f"({int(d.total_seconds())}s)"
    except Exception:
        return ""


def _pkg_note(items: list[dict]) -> str:
    failed = sum(1 for o in items if o.get("downloaded") == "failed")
    filt = sum(1 for o in items if o.get("downloaded") == "skipped-filtered")
    done = sum(1 for o in items if o.get("downloaded") in ("ok", "skipped-exists"))
    patched = sum(1 for o in items if _truthy(o.get("checksum_patched")))
    mode = items[0].get("mode", "")
    verb = "embedded" if mode == "internalize" else "rewritten"
    parts = []
    if done:
        parts.append(ok(f"✓ {done} {verb}"))
    if patched:
        parts.append(dim(f"{patched} checksum{'s' if patched != 1 else ''} patched"))
    if filt:
        parts.append(warn(f"{filt} filtered"))
    if failed:
        parts.append(err(f"✗ {failed} failed"))
    return "  ".join(parts) or dim("nothing to do")


def _remediation(op: dict) -> str:
    if op.get("mode") == "internalize":
        return dim("place file manually in the package's files/ folder")
    return dim(f"drop file at: {op.get('new_url', '')}")
