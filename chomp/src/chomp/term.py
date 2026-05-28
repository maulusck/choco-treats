"""term.py — Output via optional `rich`; monochrome fallback if absent."""

import contextlib
import re
import sys

try:
    from rich.console import Console
    from rich.markup import escape as _esc

    console = Console(highlight=False)
    err_console = Console(stderr=True, highlight=False)
    _RICH = True
except ImportError:  # rich is optional — fall back to plain text.
    _RICH = False
    _esc = str
    _TAG = re.compile(r"\[/?[a-z ]+\]")

    class _Plain:
        def __init__(self, file):
            self.file = file

        def print(self, *a, **_):
            print(_TAG.sub("", " ".join(str(x) for x in a)), file=self.file)

    console, err_console = _Plain(sys.stdout), _Plain(sys.stderr)
    sys.stderr.write(
        "warning: 'rich' not installed — using plain output. "
        "Install with: pip install rich\n"
    )

_VERBOSE = False


# ── Colors ──────────────────────────────────────────────────────────────────
def _w(t, style):
    return f"[{style}]{_esc(str(t))}[/{style}]" if _RICH else str(t)


def ok(t):        return _w(t, "green")
def warn(t):      return _w(t, "yellow")
def err(t):       return _w(t, "red")
def info(t):      return _w(t, "cyan")
def dim(t):       return _w(t, "dim")
def bold(t):      return _w(t, "bold")
def pkg(t):       return _w(t, "bold blue")
def url_old(t):   return _w(t, "yellow")
def url_new(t):   return _w(t, "cyan")


# ── Symbols ───────────────────────────────────────────────────────────────────
CHECK, CROSS, SKIP = ok("✓"), err("✗"), dim("–")
ARROW, WARN, DL = info("→"), warn("!"), info("↓")


# ── Verbose logging ───────────────────────────────────────────────────────────
def set_verbose(flag):
    global _VERBOSE
    _VERBOSE = flag


def vlog(msg):
    if _VERBOSE:
        err_console.print(dim(f"  · {msg}"))


def vlog_http(method, url, status=None, size=None):
    if not _VERBOSE:
        return
    if status is None:
        err_console.print(dim(f"  http → {method} {url}"))
    else:
        c = "green" if 200 <= status < 300 else "yellow" if status < 500 else "red"
        sz = f"  {size} bytes" if size is not None else ""
        err_console.print(_w(f"  http ← {status} {url}{sz}", c))


# ── Spinner ───────────────────────────────────────────────────────────────────
@contextlib.contextmanager
def spinner(label):
    if _RICH and console.is_terminal:
        with console.status(info(label)):
            yield
    else:
        yield


# ── Layout ────────────────────────────────────────────────────────────────────
def fatal(msg, hint=""):
    err_console.print(f"\n{err('error:')} {msg}")
    if hint:
        err_console.print(dim(f"  {hint}"))


def abort():
    err_console.print(f"\n{warn('interrupted')} {dim('(ctrl-c)')}")


def rule(char="─", width=56):
    return _w(char * width, "blue")


def section(title):
    bar = rule()
    console.print(f"\n{bar}\n  {_w(title, 'bold magenta')}\n{bar}")
