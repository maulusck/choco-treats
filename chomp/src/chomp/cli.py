"""chomp — Chocolatey Handler for Offline Package Mirroring & Processing."""

import argparse
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import (
    CLI_HELP,
    DEFAULT_RATE_LIMIT,
    ensure_repo_structure,
    get_manifest_path,
    get_out_dir,
    get_repo_root,
    normalize_mode,
    repo_path,
)
from .download import download_batch, installer_path, print_failed
from .fetch import configure as configure_fetch
from .fetch import resolve_and_download_packages
from .manifest import print_summary, write_csv, write_json
from .repack import build_nupkg, collect_urls
from .term import (
    abort,
    bold,
    console,
    dim,
    err,
    err_console,
    fatal,
    info,
    ok,
    section,
    set_verbose,
    warn,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chomp",
        description="Chocolatey Handler for Offline Package Mirroring & Processing.",
        epilog="(( \u309c\u25c7\u309c)  tip: `chomp chomp` if you're feeling peckish.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "mode",
        choices=["internalize", "rewrite", "seal", "repack", "chomp"],
        help=CLI_HELP["mode"],
    )
    p.add_argument("packages", nargs="*", metavar="PACKAGE[@VERSION]", help=CLI_HELP["packages"])

    p.add_argument("-p", "--packages-dir", type=Path, metavar="DIR", help=CLI_HELP["packages_dir"])
    p.add_argument("-o", "--out-dir", type=Path, metavar="DIR", help=CLI_HELP["out_dir"])
    p.add_argument("-i", "--installers", type=Path, metavar="DIR", help=CLI_HELP["installers"])
    p.add_argument("--fetch-dir", type=Path, metavar="DIR", help=CLI_HELP["fetch_dir"])
    p.add_argument("--in-place", action="store_true", help=CLI_HELP["in_place"])

    p.add_argument("-u", "--base-url", metavar="URL", help=CLI_HELP["base_url"])
    p.add_argument("-s", "--source", metavar="URL", help=CLI_HELP["source"])
    p.add_argument("-k", "--insecure", action="store_true", help=CLI_HELP["insecure"])
    p.add_argument("--pwsh", action="store_true", help=CLI_HELP["pwsh"])
    p.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_RATE_LIMIT,
        metavar="RPS",
        help=CLI_HELP["rate_limit"],
    )

    p.add_argument("--skip-download", action="store_true", help=CLI_HELP["skip_download"])
    p.add_argument("--interactive", action="store_true", help=CLI_HELP["interactive"])
    p.add_argument("--force", action="store_true", help=CLI_HELP["force"])
    p.add_argument("--deps", action="store_true", help=CLI_HELP["deps"])

    p.add_argument("--manifest", type=Path, help=CLI_HELP["manifest"])
    p.add_argument("--manifest-json", type=Path, help=CLI_HELP["manifest_json"])

    p.add_argument("--dry-run", action="store_true", help=CLI_HELP["dry_run"])
    p.add_argument("-q", "--quiet", action="store_true", help=CLI_HELP["quiet"])
    p.add_argument("-v", "--verbose", action="store_true", help=CLI_HELP["verbose"])
    p.add_argument("-V", "--version", action="version", version=_get_version())
    return p


def _get_version(pkg_name="chomp", display_name="CHOMP"):
    try:
        return f"{display_name} {version(pkg_name)}"
    except PackageNotFoundError:
        return f"{display_name} dev"


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # 🐶 easter egg: `chomp chomp`
    if args.mode == "chomp":
        from .art import chomp as _chomp

        _chomp()
        return 0

    mode = normalize_mode(args.mode)
    is_dry, force = args.dry_run, args.force

    if args.verbose:
        set_verbose(True)

    if mode == "rewrite" and not args.base_url:
        err_console.print(err("rewrite mode requires --base-url"))
        return 2

    configure_fetch(
        repo_url=args.source, rate=args.rate_limit, insecure=args.insecure, use_pwsh=args.pwsh
    )

    base_url = (args.base_url or "").rstrip("/") if mode == "rewrite" else None
    repo_root = get_repo_root()

    # ---- Paths ----
    pkg_dir = args.packages_dir.resolve() if args.packages_dir else repo_path(repo_root, "nupkgs")
    pkg_dir = pkg_dir if pkg_dir.exists() else None
    installer_dir = (
        args.installers.resolve() if args.installers else repo_path(repo_root, "installers")
    )
    fetch_dir = args.fetch_dir.resolve() if args.fetch_dir else repo_path(repo_root, "nupkgs")
    out_dir = args.out_dir.resolve() if args.out_dir else get_out_dir(repo_root, mode)
    if args.in_place and pkg_dir:
        out_dir = pkg_dir
    manifest_csv = args.manifest.resolve() if args.manifest else get_manifest_path(repo_root, mode)

    # ---- Setup ----
    if not is_dry:
        ensure_repo_structure(repo_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        fetch_dir.mkdir(parents=True, exist_ok=True)

    # ---- Header ----
    tags = "".join(
        [
            warn(" [DRY RUN]") if is_dry else "",
            warn(" [--force]") if force else "",
            warn(" [insecure]") if args.insecure else "",
            info(" [--pwsh]") if args.pwsh else "",
            info(" [--verbose]") if args.verbose else "",
        ]
    )
    mode_display = f"{mode} ({args.mode})" if args.mode != mode else mode
    console.print(f"\n{bold('chomp')} {dim(mode_display)}{tags}")
    console.print(dim(f"  repo root : {repo_root}"))
    console.print(dim(f"  packages  : {pkg_dir or '(fetch only)'}"))
    console.print(dim(f"  installers: {installer_dir}"))
    console.print(dim(f"  out       : {out_dir}"))
    if base_url:
        console.print(dim(f"  base URL  : {base_url}"))

    # ---- Package collection ----
    # Named packages → fetch exactly those. --packages-dir → sweep that dir.
    # Both → fetch + sweep. Neither → error. (The default pkg_dir/fetch_dir both
    # point at nupkgs/, so the args.packages_dir guard prevents sweeping the cache.)
    nupkgs = []
    if args.packages:
        section("Fetching packages")
        if not is_dry:
            fetch_dir.mkdir(parents=True, exist_ok=True)
            nupkgs.extend(
                resolve_and_download_packages(
                    args.packages,
                    dest_dir=fetch_dir,
                    quiet=args.quiet,
                    force=force,
                    include_deps=args.deps,
                )
            )
    if args.packages_dir and pkg_dir:
        nupkgs.extend(sorted(pkg_dir.glob("*.nupkg")))

    if not nupkgs:
        err_console.print(err("No packages to process."))
        return 1

    # Dedupe by stem
    seen, unique = set(), []
    for n in nupkgs:
        if n.stem not in seen:
            seen.add(n.stem)
            unique.append(n)
    nupkgs = unique

    # ---- Phase 1: scan (read-only) ----
    all_mappings = []
    nupkg_mappings: dict[Path, list[dict]] = {}
    section("Phase 1 — Scanning packages")
    for nupkg in nupkgs:
        result = collect_urls(
            nupkg=nupkg, base_url=base_url, out_dir=out_dir, mode=mode, force=force
        )
        if result is None:
            continue
        nupkg_mappings[nupkg] = result
        all_mappings.extend(result)

    if not nupkg_mappings:
        console.print(warn("Nothing to do."))
        return 0

    # ---- Phase 2/3: download + build (skipped on dry run) ----
    if not is_dry and not args.skip_download:
        section("Phase 2 — Downloading installers")
        try:
            all_mappings = download_batch(
                items=all_mappings,
                installer_dir=installer_dir,
                quiet=args.quiet,
                interactive=args.interactive,
                force=force,
            )
        except KeyboardInterrupt:
            abort()
            done = sum(1 for m in all_mappings if m.get("downloaded") == "ok")
            console.print(warn(f"  {done} installer(s) downloaded before interrupt"))
            raise

        section("Phase 3 — Building packages")

        def resolve(m):
            return installer_path(m, installer_dir)

        with tempfile.TemporaryDirectory(prefix="chomp_") as tmp:
            try:
                for nupkg, mappings in nupkg_mappings.items():
                    failed = [m for m in mappings if m.get("downloaded") == "failed"]
                    if failed:
                        console.print(
                            warn(
                                f"  ✗ incomplete — not written: {nupkg.name} "
                                f"({len(failed)} failed download(s))"
                            )
                        )
                        continue
                    build_nupkg(
                        nupkg=nupkg,
                        mappings=mappings,
                        local_file_resolver=resolve,
                        out_dir=out_dir,
                        work_dir=Path(tmp),
                        mode=mode,
                    )
            except KeyboardInterrupt:
                abort()
                raise

    # ---- Output ----
    if not is_dry:
        write_csv(all_mappings, manifest_csv)
        if args.manifest_json:
            write_json(all_mappings, args.manifest_json)

    print_summary(all_mappings)
    print_failed(all_mappings)

    if is_dry:
        console.print(warn("Dry run complete — nothing written."))
    else:
        console.print(f"{ok('done')}: {out_dir}")
    return 0


def entry_point():
    import os
    import traceback

    show_tb = os.environ.get("CHOMP_TRACEBACK") or "--verbose" in sys.argv or "-v" in sys.argv
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        abort()
        sys.exit(130)
    except Exception as exc:
        if show_tb:
            traceback.print_exc()
        else:
            msg = str(exc).strip() or type(exc).__name__
            cause = exc.__cause__ or exc.__context__
            if cause and str(cause).strip():
                msg = f"{msg}: {str(cause).strip()}"
            fatal(msg, hint="re-run with -v for full traceback, or set CHOMP_TRACEBACK=1")
        sys.exit(1)
