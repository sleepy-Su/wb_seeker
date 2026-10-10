import tkinter as tk

import pytest

from weibo_downloader.gui import DownloaderApp
from weibo_downloader.paths import default_download_dir


def test_gui_builds_with_default_download_directory() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk is unavailable: {exc}")

    try:
        root.withdraw()
        app = DownloaderApp(root)
        assert app.output_var.get() == str(default_download_dir())
    finally:
        root.destroy()
