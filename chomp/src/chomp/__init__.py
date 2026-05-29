"""chomp — internalize or rewrite Chocolatey packages for air-gapped repos."""

from .download import download_batch, installer_path, print_failed
from .fetch import (
    configure,
    download_nupkg,
    resolve_and_download_packages,
    resolve_package,
    resolve_with_deps,
)
from .manifest import (
    explain,
    load_manifest,
    print_summary,
    summarize,
    write_csv,
    write_json,
)
from .repack import build_nupkg, classify_url, collect_urls

__all__ = [
    "configure",
    "collect_urls",
    "build_nupkg",
    "classify_url",
    "download_batch",
    "installer_path",
    "print_failed",
    "resolve_package",
    "resolve_with_deps",
    "download_nupkg",
    "resolve_and_download_packages",
    "write_csv",
    "write_json",
    "load_manifest",
    "summarize",
    "explain",
    "print_summary",
]
