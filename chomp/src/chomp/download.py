"""
download.py — Download installer files referenced in .ps1 scripts.
Deduplication, URL classification, interactive review, skip-if-exists, --force.
"""

from pathlib import Path

from .fetch import http_download
from .repack import _filename_from_url, classify_url
from .term import ARROW, CHECK, CROSS, SKIP, WARN, Spinner, dim, err, info, ok
from .term import pkg as cpkg
from .term import url_new, url_old, warn


def installer_path(mapping: dict, installer_dir: Path) -> Path:
    """installers/<pkg>/<version>/<filename>"""
    pkg, ver, name = mapping["package"], mapping.get("version", ""), mapping["filename"]
    return installer_dir / pkg / ver / name if ver else installer_dir / pkg / name


def _download_one(url: str, dest: Path, use_pwsh: bool = False) -> tuple[bool, str]:
    try:
        with Spinner(dest.name):
            http_download(url, dest, use_pwsh=use_pwsh)
        sz = dest.stat().st_size
        size_str = dim(
            f"  {sz / 1_048_576:.1f} MB" if sz >= 1_048_576 else f"  {sz // 1024} KB"
        )
        print(f"  {CHECK} {ok(dest.name)}{size_str}")
        return True, ""
    except Exception as e:
        msg = str(e).strip().splitlines()[-1] if str(e).strip() else "unknown error"
        print(f"  {CROSS} {err(dest.name)}  {dim(msg)}")
        return False, msg


def _prompt_url(item: dict, dest: Path) -> dict:
    url, pkg_, version = item["old_url"], item["package"], item.get("version", "")
    ok_flag, skip_reason = classify_url(url)
    print(f"\n  {cpkg(f'[{pkg_} {version}]')}")
    if not ok_flag:
        print(f"  {WARN} {warn(f'auto-skip suggested: {skip_reason}')}")
    print(f"  {url_old(url)}")
    while True:
        raw = (
            input(f"  {dim('[Enter]')}=download  {dim('s')}=skip  {dim('e')}=edit > ")
            .strip()
            .lower()
        )
        if raw in ("", "d"):
            return {**item, "action": "download", "resolved_url": url}
        if raw == "s":
            return {
                **item,
                "action": "skip",
                "resolved_url": url,
                "skip_reason": "user skipped",
            }
        if raw == "e":
            new_url = input(f"  New URL [{url}]: ").strip() or url
            return {
                **item,
                "action": "download",
                "resolved_url": new_url,
                "filename": _filename_from_url(new_url),
            }
        print(f"  {warn('?')} Enter, s, or e.")


def _item_key(item: dict) -> tuple:
    return (item["package"], item.get("version", ""), item["filename"])


def download_batch(
    items: list[dict],
    installer_dir: Path,
    use_pwsh: bool = False,
    quiet: bool = False,
    interactive: bool = False,
    force: bool = False,
) -> list[dict]:
    """Download all installer URLs. Returns items annotated with 'downloaded' status."""

    # Interactive pre-pass
    if interactive:
        print(f"\n{info('── Review URLs (all decisions before downloads start) ──')}")
        resolved, seen = [], set()
        for item in items:
            key = _item_key(item)
            dest = installer_path(item, installer_dir)
            if key in seen:
                resolved.append(
                    {**item, "action": "duplicate", "resolved_url": item["old_url"]}
                )
            elif dest.exists() and not force:
                resolved.append(
                    {**item, "action": "exists", "resolved_url": item["old_url"]}
                )
            else:
                resolved.append(_prompt_url(item, dest))
                seen.add(key)
        items = resolved
        print(f"\n{info('── Starting downloads ──')}")

    seen, results = set(), []
    for item in items:
        url = item.get("resolved_url", item["old_url"])
        key = _item_key(item)
        action = item.get("action")
        dest = installer_path(item, installer_dir)

        if action == "duplicate" or (action is None and key in seen):
            results.append(
                {**item, "downloaded": "skipped-duplicate", "skip_reason": ""}
            )
            continue
        if action == "exists" or (action is None and dest.exists() and not force):
            if not quiet:
                print(f"  {SKIP} {dim('exists:')} {dim(str(dest))}")
            results.append({**item, "downloaded": "skipped-exists", "skip_reason": ""})
            continue
        if action == "skip":
            results.append(
                {
                    **item,
                    "downloaded": "skipped-interactive",
                    "skip_reason": item.get("skip_reason", "user skipped"),
                }
            )
            continue

        seen.add(key)

        should_dl, skip_reason = classify_url(url)
        if not should_dl:
            if not quiet:
                print(f"  {SKIP} {warn(f'filtered ({skip_reason}):')} {dim(url)}")
            results.append(
                {**item, "downloaded": "skipped-filtered", "skip_reason": skip_reason}
            )
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"  {CROSS} {err('mkdir failed:')} {dim(str(e))}")
            results.append(
                {**item, "downloaded": "failed", "skip_reason": f"mkdir: {e}"}
            )
            continue
        success, err_msg = _download_one(url, dest, use_pwsh)
        results.append(
            {
                **item,
                "downloaded": "ok" if success else "failed",
                "skip_reason": err_msg if not success else "",
            }
        )
    return results


def print_failed(results: list[dict]) -> None:
    failed = [r for r in results if r.get("downloaded") == "failed"]
    filtered = [r for r in results if r.get("downloaded") == "skipped-filtered"]
    if not failed and not filtered:
        return
    bar = "═" * 58
    print(f"\n{err(bar)}\n  {err('MANUAL DOWNLOAD REQUIRED')}\n{err(bar)}")
    for label, items in (
        ("Skipped (not a file URL)", filtered),
        ("Failed downloads", failed),
    ):
        if not items:
            continue
        print(f"\n  {warn(f'{label} — {len(items)} URL(s):')}")
        for r in items:
            reason = r.get("skip_reason", "")
            if reason:
                print(f"    {dim(f'[{reason}]')}")
            print(f"    {url_old(r['old_url'])}")
            if r.get("mode") == "internalize":
                print(f"    {ARROW} place file manually in the package's files/ folder")
            else:
                print(f"    {ARROW} drop file at: {url_new(r.get('new_url', ''))}")
    print(err(bar) + "\n")
