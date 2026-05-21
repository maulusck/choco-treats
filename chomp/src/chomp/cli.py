"""chomp — Chocolatey Handler for Offline Package Mirroring"""

import argparse
import sys
import tempfile
from pathlib import Path

from .config import (
    CLI_HELP,
    ensure_repo_structure,
    get_manifest_path,
    get_out_dir,
    get_repo_root,
    normalize_mode,
    repo_path,
)
from .download import download_batch, installer_path, print_failed
from .fetch import resolve_and_download_packages, resolve_with_deps
from .manifest import print_summary, write_csv, write_json
from .repack import finalize_nupkg, process_nupkg_phase1
from .term import bold, dim, err, info, ok, section, set_verbose, warn


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chomp",
        description="Chocolatey Handler for Offline Package Mirroring & Processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "mode",
        choices=["internalize", "rewrite", "seal", "repack"],
        help=CLI_HELP["mode"],
    )
    p.add_argument(
        "packages", nargs="*", metavar="PACKAGE[@VERSION]", help=CLI_HELP["packages"]
    )

    p.add_argument(
        "-p", "--packages-dir", type=Path, metavar="DIR", help=CLI_HELP["packages_dir"]
    )
    p.add_argument(
        "-o", "--out-dir", type=Path, metavar="DIR", help=CLI_HELP["out_dir"]
    )
    p.add_argument(
        "-i", "--installers", type=Path, metavar="DIR", help=CLI_HELP["installers"]
    )
    p.add_argument("--fetch-dir", type=Path, metavar="DIR", help=CLI_HELP["fetch_dir"])
    p.add_argument("--in-place", action="store_true", help=CLI_HELP["in_place"])

    p.add_argument("-u", "--base-url", metavar="URL", help=CLI_HELP["base_url"])

    p.add_argument("--pwsh", action="store_true", help=CLI_HELP["pwsh"])
    p.add_argument(
        "--skip-download", action="store_true", help=CLI_HELP["skip_download"]
    )
    p.add_argument("--interactive", action="store_true", help=CLI_HELP["interactive"])
    p.add_argument("--force", action="store_true", help=CLI_HELP["force"])
    p.add_argument("--deps", action="store_true", help=CLI_HELP["deps"])

    p.add_argument("--manifest", type=Path, help=CLI_HELP["manifest"])
    p.add_argument("--manifest-json", type=Path, help=CLI_HELP["manifest_json"])

    p.add_argument("--dry-run", action="store_true", help=CLI_HELP["dry_run"])
    p.add_argument("-q", "--quiet", action="store_true", help=CLI_HELP["quiet"])
    p.add_argument("-v", "--verbose", action="store_true", help=CLI_HELP["verbose"])

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    mode = normalize_mode(args.mode)
    is_dry = args.dry_run
    force = args.force

    if args.verbose:
        set_verbose(True)

    if mode == "rewrite" and not args.base_url:
        print(err("rewrite mode requires --base-url"), file=sys.stderr)
        return 2

    base_url = (args.base_url or "").rstrip("/") if mode == "rewrite" else None
    repo_root = get_repo_root()

    # ---- Paths ----
    pkg_dir = (
        args.packages_dir.resolve()
        if args.packages_dir
        else repo_path(repo_root, "nupkgs")
    )
    pkg_dir = pkg_dir if pkg_dir.exists() else None
    installer_dir = (
        args.installers.resolve()
        if args.installers
        else repo_path(repo_root, "installers")
    )
    fetch_dir = (
        args.fetch_dir.resolve() if args.fetch_dir else repo_path(repo_root, "nupkgs")
    )
    out_dir = args.out_dir.resolve() if args.out_dir else get_out_dir(repo_root, mode)

    if args.in_place and pkg_dir:
        out_dir = pkg_dir

    manifest_csv = (
        args.manifest.resolve() if args.manifest else get_manifest_path(repo_root, mode)
    )

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
            info(" [--pwsh]") if args.pwsh else "",
            info(" [--verbose]") if args.verbose else "",
        ]
    )
    mode_display = f"{mode} ({args.mode})" if args.mode != mode else mode
    print(f"\n{bold('chomp')} {dim(mode_display)}{tags}")
    print(dim(f"  repo root : {repo_root}"))
    print(dim(f"  packages  : {pkg_dir or '(fetch only)'}"))
    print(dim(f"  installers: {installer_dir}"))
    print(dim(f"  out       : {out_dir}"))
    if base_url:
        print(dim(f"  base URL  : {base_url}"))

    # ---- Package collection ----
    # Rule: named packages → fetch exactly those.
    #       --packages-dir (explicit) → sweep that dir.
    #       Both → fetch named + sweep explicit dir.
    #       Neither → error.
    # The default pkg_dir/fetch_dir both point at nupkgs/, so without the
    # args.packages_dir guard, every previously cached nupkg would be swept
    # on every run regardless of what was requested.
    nupkgs = []

    if args.packages:
        section("Fetching packages")
        if not is_dry:
            fetch_dir.mkdir(parents=True, exist_ok=True)
            nupkgs.extend(
                resolve_and_download_packages(
                    args.packages,
                    dest_dir=fetch_dir,
                    use_pwsh=args.pwsh,
                    quiet=args.quiet,
                    force=force,
                    include_deps=args.deps,
                )
            )

    if args.packages_dir and pkg_dir:
        # Only sweep pkg_dir when explicitly passed — not the default nupkgs/ cache.
        nupkgs.extend(sorted(pkg_dir.glob("*.nupkg")))

    if not nupkgs:
        print(err("No packages to process."), file=sys.stderr)
        return 1

    # Dedupe by stem
    seen, unique = set(), []
    for n in nupkgs:
        if n.stem not in seen:
            seen.add(n.stem)
            unique.append(n)
    nupkgs = unique

    # ---- Phase 1: rewrite URLs ----
    all_mappings = []
    processed_nupkgs = []  # only nupkgs written this run

    section("Phase 1 — Rewriting URLs")
    with tempfile.TemporaryDirectory(prefix="chomp_p1_") as tmp:
        for nupkg in nupkgs:
            mappings = process_nupkg_phase1(
                nupkg=nupkg,
                base_url=base_url,
                out_dir=out_dir,
                work_dir=Path(tmp),
                mode=mode,
                dry_run=is_dry,
                force=force,
            )
            if mappings is not None:
                all_mappings.extend(mappings)
                processed_nupkgs.append(out_dir / nupkg.name)

    if not all_mappings:
        print(warn("No external URLs found."))
        return 0

    # ---- Phase 2: download + finalize ----
    if not args.skip_download and not is_dry:
        section("Phase 2 — Downloading installers")
        all_mappings = download_batch(
            items=all_mappings,
            installer_dir=installer_dir,
            use_pwsh=args.pwsh,
            quiet=args.quiet,
            interactive=args.interactive,
            force=force,
        )

        section("Phase 2b — Finalizing packages")

        def resolve(m):
            return installer_path(m, installer_dir)

        with tempfile.TemporaryDirectory(prefix="chomp_p2_") as tmp2:
            for nupkg in processed_nupkgs:
                if not nupkg.exists():
                    continue
                pkg_id = nupkg.stem.split(".")[0]
                pkg_maps = [m for m in all_mappings if m["package"] == pkg_id]
                if not pkg_maps:
                    continue
                finalize_nupkg(
                    nupkg=nupkg,
                    mappings=pkg_maps,
                    local_file_resolver=resolve,
                    out_dir=out_dir,
                    work_dir=Path(tmp2),
                    mode=mode,
                )

    # ---- Output ----
    if not is_dry:
        write_csv(all_mappings, manifest_csv)
        if args.manifest_json:
            write_json(all_mappings, args.manifest_json)

    print_summary(all_mappings)
    print_failed(all_mappings)

    if is_dry:
        print(warn("Dry run complete — nothing written."))
    else:
        print(f"{ok('done')}: {out_dir}")

    return 0


def entry_point():
    sys.exit(main())
