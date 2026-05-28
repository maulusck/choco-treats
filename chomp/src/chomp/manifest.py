"""manifest.py — Write audit trail (CSV / JSON) and print run summary."""

import csv
import json
from pathlib import Path

from .term import bold, console, dim, err, ok, rule, warn

FIELDS = [
    "package", "version", "ps1", "mode", "old_url", "new_url", "filename",
    "downloaded", "skip_reason", "checksum_patched", "new_checksum",
]


def write_csv(mappings: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(mappings)


def write_json(mappings: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mappings, indent=2, default=str), encoding="utf-8")


def _count(mappings, status):
    return sum(1 for m in mappings if m.get("downloaded") == status)


def print_summary(mappings: list[dict]) -> None:
    counts = {
        "URLs found": len(mappings),
        "Downloaded": _count(mappings, "ok"),
        "Already exist": _count(mappings, "skipped-exists"),
        "Duplicates skipped": _count(mappings, "skipped-duplicate"),
        "Filtered (no-file)": _count(mappings, "skipped-filtered"),
        "Failed": _count(mappings, "failed"),
        "Checksums patched": sum(1 for m in mappings if m.get("checksum_patched")),
    }
    colors = {"Downloaded": ok, "Filtered (no-file)": warn, "Failed": err, "Checksums patched": ok}
    bar = rule()
    console.print(f"\n{bar}\n  {bold('Summary')}\n{bar}")
    for label, value in counts.items():
        color = colors.get(label)
        val = color(str(value)) if color and value else dim(str(value))
        console.print(f"  {dim(f'{label:<26}')} {val}")
    console.print(bar)
