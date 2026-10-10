from __future__ import annotations

import sys
from pathlib import Path


def application_dir() -> Path:
    """Return the directory containing main.py or the packaged executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_download_dir() -> Path:
    return application_dir() / "downloads"


def default_cookie_path() -> Path:
    return application_dir() / "cookies.txt"
