"""
term.py — Terminal output: colors, symbols, spinner, verbose logging.
Stdlib only. Respects NO_COLOR / FORCE_COLOR / non-TTY.
"""

import itertools
import os
import sys
import threading
import time
from typing import Optional

# ── Color detection ───────────────────────────────────────────────────────────


def _colors_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


_USE_COLOR = _colors_enabled()
_VERBOSE = False

_RESET = "\033[0m"
_CODES = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}


def _c(text: str, *attrs) -> str:
    if not _USE_COLOR or not attrs:
        return text
    prefix = "".join(_CODES[a] for a in attrs if a in _CODES)
    return f"{prefix}{text}{_RESET}" if prefix else text


# ── Public color helpers ──────────────────────────────────────────────────────


def ok(t):
    return _c(t, "green")


def warn(t):
    return _c(t, "yellow")


def err(t):
    return _c(t, "red")


def info(t):
    return _c(t, "cyan")


def dim(t):
    return _c(t, "dim")


def bold(t):
    return _c(t, "bold")


def pkg(t):
    return _c(t, "blue", "bold")


def url_old(t):
    return _c(t, "yellow")


def url_new(t):
    return _c(t, "cyan")


# ── Symbols ───────────────────────────────────────────────────────────────────

CHECK = ok("✓")
CROSS = err("✗")
SKIP = dim("–")
ARROW = info("→")
WARN = warn("!")
DL = info("↓")

# ── Verbose logging ───────────────────────────────────────────────────────────


def set_verbose(flag: bool) -> None:
    global _VERBOSE
    _VERBOSE = flag


def is_verbose() -> bool:
    return _VERBOSE


def vlog(msg: str) -> None:
    if _VERBOSE:
        print(_c(f"  [dbg] {msg}", "gray"), file=sys.stderr)


def vlog_http(
    method: str, url: str, status: Optional[int] = None, size: Optional[int] = None
) -> None:
    if not _VERBOSE:
        return
    if status is None:
        print(_c(f"  [http] → {method} {url}", "gray"), file=sys.stderr)
    else:
        color = (
            "green" if 200 <= status < 300 else ("yellow" if status < 500 else "red")
        )
        size_str = f"  {size} bytes" if size is not None else ""
        print(_c(f"  [http] ← {status} {url}{size_str}", color), file=sys.stderr)


def vlog_pwsh(
    script: str, stdout: str = "", stderr_: str = "", returncode: int = 0
) -> None:
    if not _VERBOSE:
        return
    lines = script.strip().splitlines()
    print(_c("  [pwsh] script:", "gray"), file=sys.stderr)
    for line in lines[:8]:
        print(_c(f"    {line}", "gray"), file=sys.stderr)
    if len(lines) > 8:
        print(_c(f"    ... (+{len(lines) - 8} more lines)", "gray"), file=sys.stderr)
    if stdout or stderr_:
        color = "green" if returncode == 0 else "red"
        print(_c(f"  [pwsh] exit={returncode}", color), file=sys.stderr)
        for line in (stdout + stderr_).strip().splitlines()[:12]:
            print(_c(f"    {line}", "gray"), file=sys.stderr)


# ── Spinner ───────────────────────────────────────────────────────────────────


class Spinner:
    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    _INTERVAL = 0.08

    def __init__(self, label: str):
        self._label = label
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._active = sys.stderr.isatty() and _USE_COLOR

    def _spin(self):
        start = time.monotonic()
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            elapsed = time.monotonic() - start
            sys.stderr.write(
                f"\r  {frame} {info(self._label)}{_c(f'  {elapsed:5.1f}s', 'gray')}   "
            )
            sys.stderr.flush()
            time.sleep(self._INTERVAL)

    def __enter__(self):
        if self._active:
            self._thread.start()
        else:
            sys.stderr.write(f"  {self._label} ... ")
            sys.stderr.flush()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._active and self._thread.is_alive():
            self._thread.join(timeout=1)
            sys.stderr.write("\r" + " " * 72 + "\r")
            sys.stderr.flush()
        elif not self._active:
            sys.stderr.write("done\n")
            sys.stderr.flush()


# ── Layout ────────────────────────────────────────────────────────────────────


def fatal(msg: str, hint: str = "") -> None:
    """Print a clean fatal error line (no traceback)."""
    print(f"\n{err('error:')} {msg}", file=sys.stderr)
    if hint:
        print(f"  {dim(hint)}", file=sys.stderr)


def abort() -> None:
    """Print a clean Ctrl-C / interrupt message."""
    print(f"\n{warn('interrupted')} {dim('(ctrl-c)')}", file=sys.stderr)


def section(title: str) -> None:
    bar = _c("─" * 56, "blue")
    print(f"\n{bar}\n  {_c(title, 'magenta', 'bold')}\n{bar}")


def rule(char: str = "─", width: int = 56) -> str:
    return _c(char * width, "blue")
