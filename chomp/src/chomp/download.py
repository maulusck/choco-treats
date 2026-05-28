"""download.py — Download installer files referenced in .ps1 scripts."""

from pathlib import Path

from .fetch import http_download
from .repack import _filename_from_url, apply_filename, classify_url
from .term import ARROW, CHECK, CROSS, SKIP, WARN, console, dim, err, info, ok
from .term import pkg as cpkg
from .term import spinner, url_new, url_old, warn


def installer_path(mapping: dict, installer_dir: Path) -> Path:
    """installers/<pkg>/<version>/<filename>"""
    pkg, ver, name = mapping["package"], mapping.get("version", ""), mapping["filename"]
    return installer_dir / pkg / ver / name if ver else installer_dir / pkg / name


def _download_one(url: str, dest: Path) -> tuple[bool, str, str | None]:
    try:
        with spinner(dest.name):
            server_name = http_download(url, dest)
        sz = dest.stat().st_size
        size = dim(f"  {sz / 1_048_576:.1f} MB" if sz >= 1_048_576 else f"  {sz // 1024} KB")
        console.print(f"  {CHECK} {ok(dest.name)}{size}")
        return True, "", server_name
    except Exception as e:
        msg = str(e).strip().splitlines()[-1] if str(e).strip() else "unknown error"
        console.print(f"  {CROSS} {err(dest.name)}  {dim(msg)}")
        return False, msg, None


def _prompt_url(item: dict) -> dict:
    url = item["old_url"]
    ok_flag, skip_reason = classify_url(url)
    label = f"[{item['package']} {item.get('version', '')}]"
    console.print(f"\n  {cpkg(label)}")
    if not ok_flag:
        console.print(f"  {WARN} {warn(f'auto-skip suggested: {skip_reason}')}")
    console.print(f"  {url_old(url)}")
    while True:
        raw = (
            input(f"  {dim('[Enter]')}=download  {dim('s')}=skip  {dim('e')}=edit > ")
            .strip()
            .lower()
        )
        if raw in ("", "d"):
            item.update(action="download", resolved_url=url)
            return item
        if raw == "s":
            item.update(action="skip", resolved_url=url, skip_reason="user skipped")
            return item
        if raw == "e":
            new_url = input(f"  New URL [{url}]: ").strip() or url
            item.update(action="download", resolved_url=new_url)
            apply_filename(item, _filename_from_url(new_url))
            return item
        console.print(f"  {warn('?')} Enter, s, or e.")


def _item_key(item: dict) -> tuple:
    return (item["package"], item.get("version", ""), item["filename"])


def download_batch(
    items: list[dict],
    installer_dir: Path,
    quiet: bool = False,
    interactive: bool = False,
    force: bool = False,
) -> list[dict]:
    """Download all installer URLs, mutating each item in place with 'downloaded'.

    Items are mutated (not copied) so callers holding the same dicts — e.g. the
    per-nupkg mapping groups used by the build phase — see resolved URLs and
    renamed filenames without any regrouping.
    """

    if interactive:
        console.print(f"\n{info('── Review URLs (all decisions before downloads start) ──')}")
        seen = set()
        for item in items:
            dest = installer_path(item, installer_dir)
            if _item_key(item) in seen:
                item.update(action="duplicate", resolved_url=item["old_url"])
            elif dest.exists() and not force:
                item.update(action="exists", resolved_url=item["old_url"])
            else:
                _prompt_url(item)
                seen.add(_item_key(item))
        console.print(f"\n{info('── Starting downloads ──')}")

    seen = set()
    for item in items:
        action = item.get("action")
        key = _item_key(item)
        dest = installer_path(item, installer_dir)

        if action == "duplicate" or (action is None and key in seen):
            item.update(downloaded="skipped-duplicate", skip_reason="")
            continue
        if action == "exists" or (action is None and dest.exists() and not force):
            if not quiet:
                console.print(f"  {SKIP} {dim('exists:')} {dim(str(dest))}")
            item.update(downloaded="skipped-exists", skip_reason="")
            continue
        if action == "skip":
            item.update(
                downloaded="skipped-interactive",
                skip_reason=item.get("skip_reason", "user skipped"),
            )
            continue

        seen.add(key)
        url = item.get("resolved_url", item["old_url"])

        # Auto-filter only applies to non-interactive items. An explicit
        # interactive "download" decision is authoritative — the user has
        # already seen the auto-skip suggestion and overridden it.
        if action != "download":
            should_dl, skip_reason = classify_url(url)
            if not should_dl:
                if not quiet:
                    console.print(f"  {SKIP} {warn(f'filtered ({skip_reason}):')} {dim(url)}")
                item.update(downloaded="skipped-filtered", skip_reason=skip_reason)
                continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            console.print(f"  {CROSS} {err('mkdir failed:')} {dim(str(e))}")
            item.update(downloaded="failed", skip_reason=f"mkdir: {e}")
            continue

        success, err_msg, server_name = _download_one(url, dest)

        # If we couldn't derive a real filename from the URL (no extension or
        # the installer.bin fallback), adopt the name the server gave us so
        # multiple installers never collide on installer.bin.
        if success and server_name:
            cur = item["filename"]
            if (not Path(cur).suffix or cur == "installer.bin") and Path(server_name).suffix:
                apply_filename(item, server_name)
                new_dest = installer_path(item, installer_dir)
                if new_dest != dest:
                    new_dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.replace(new_dest)
                    if not quiet:
                        console.print(f"  {ARROW} {dim('named by server:')} {dim(server_name)}")

        item.update(
            downloaded="ok" if success else "failed", skip_reason="" if success else err_msg
        )
    return items


def print_failed(results: list[dict]) -> None:
    failed = [r for r in results if r.get("downloaded") == "failed"]
    filtered = [r for r in results if r.get("downloaded") == "skipped-filtered"]
    if not failed and not filtered:
        return
    bar = "═" * 58
    console.print(f"\n{err(bar)}\n  {err('MANUAL DOWNLOAD REQUIRED')}\n{err(bar)}")
    for label, items in (("Skipped (not a file URL)", filtered), ("Failed downloads", failed)):
        if not items:
            continue
        console.print(f"\n  {warn(f'{label} — {len(items)} URL(s):')}")
        for r in items:
            if r.get("skip_reason"):
                reason = r["skip_reason"]
                console.print(f"    {dim(f'[{reason}]')}")
            console.print(f"    {url_old(r['old_url'])}")
            if r.get("mode") == "internalize":
                console.print(f"    {ARROW} place file manually in the package's files/ folder")
            else:
                console.print(f"    {ARROW} drop file at: {url_new(r.get('new_url', ''))}")
    console.print(err(bar) + "\n")
