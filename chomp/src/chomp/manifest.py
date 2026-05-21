"""manifest.py — Write audit trail (CSV / JSON) and print run summary."""

import csv
import json
from pathlib import Path

from .term import CHECK, bold, dim, err, ok, rule, warn

FIELDS = [
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


def write_csv(mappings: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(mappings)


def write_json(mappings: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mappings, indent=2, default=str), encoding="utf-8")


def print_summary(mappings: list[dict]) -> None:
    counts = {
        "URLs found": len(mappings),
        "Downloaded": sum(1 for m in mappings if m.get("downloaded") == "ok"),
        "Already exist": sum(
            1 for m in mappings if m.get("downloaded") == "skipped-exists"
        ),
        "Duplicates skipped": sum(
            1 for m in mappings if m.get("downloaded") == "skipped-duplicate"
        ),
        "Filtered (no-file)": sum(
            1 for m in mappings if m.get("downloaded") == "skipped-filtered"
        ),
        "Failed": sum(1 for m in mappings if m.get("downloaded") == "failed"),
        "Checksums patched": sum(1 for m in mappings if m.get("checksum_patched")),
    }
    colors = {
        "Downloaded": ok,
        "Filtered (no-file)": warn,
        "Failed": err,
        "Checksums patched": ok,
    }
    bar = rule()
    print(f"\n{bar}\n  {bold('Summary')}\n{bar}")
    for label, value in counts.items():
        color = colors.get(label)
        val_str = color(str(value)) if color and value else dim(str(value))
        print(f"  {dim(f'{label:<26}')} {val_str}")
    print(bar)
