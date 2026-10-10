from __future__ import annotations

import argparse

from weibo_downloader.cli import main as cli_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="微博博主正文原图下载器")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="使用交互式命令行，而不是启动图形界面",
    )
    args = parser.parse_args(argv)

    if args.cli:
        return cli_main()

    try:
        import tkinter as tk
    except ImportError as exc:
        print(f"无法启动图形界面：{exc}")
        print("将改用命令行模式。")
        return cli_main()

    try:
        from weibo_downloader.gui import main as gui_main

        return gui_main()
    except tk.TclError as exc:
        print(f"无法启动图形界面：{exc}")
        print("将改用命令行模式。")
        return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
