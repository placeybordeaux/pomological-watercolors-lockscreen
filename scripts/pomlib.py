"""Shared helpers for the pomological watercolor tooling.

Everything here is stdlib-only on purpose: this machine has no uv/pip
environment wired up for the project, and the fetch stage should stay runnable
from a bare `python3` on any box.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir() -> str:
    """Where the catalogue, the scans and the prepared plates live.

    Running from a git checkout this is just ./data. Installed from the nix
    package the code sits in the store and cannot be written to, so the data
    goes under XDG_DATA_HOME instead. POMOLOGICAL_DATA overrides both, which is
    also how you keep 56 GB of scans on a different disk.
    """
    if override := os.environ.get("POMOLOGICAL_DATA"):
        return override
    local = os.path.join(REPO_ROOT, "data")
    if os.access(REPO_ROOT, os.W_OK):
        return local
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(xdg, "pomological", "data")


DATA_DIR = _data_dir()
DB_PATH = os.path.join(DATA_DIR, "pom.sqlite")
ORIGINALS_DIR = os.path.join(DATA_DIR, "originals")

# The Internet Archive mirror of the full-resolution scans, and a separate IA
# item that carries the collection's metadata CSV exported from NAL.
IA_IMAGE_ITEM = "usda-pomological-watercolor-collection"
IA_METADATA_ITEM = "usda_pomological_watercolors_20200211"

USER_AGENT = "pomological-watercolors/0.1 (personal archival + wallpaper project)"

FRUIT = "🍎🍐🍊🍋🍌🍉🍇🍓🫐🍒🍑🥭🍍🥥🥝🌰"


def http_get(url: str, timeout: int = 120, retries: int = 4, headers: dict | None = None) -> bytes:
    """GET with exponential backoff. Raises the last error if every try fails."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            # 404 is a real answer, not a transient failure - don't burn retries.
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def ia_metadata(identifier: str) -> dict:
    return json.loads(http_get(f"https://archive.org/metadata/{identifier}"))


def connect(db_path: str = DB_PATH, multithread: bool = False) -> sqlite3.Connection:
    """Open the index database. `multithread` is for the downloader, which
    funnels all writes through a single dedicated thread rather than the one
    that opened the connection."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60, check_same_thread=not multithread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} PB"


def human_time(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def is_tty() -> bool:
    return sys.stdout.isatty()
