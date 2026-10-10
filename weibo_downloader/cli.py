from __future__ import annotations

import logging
from datetime import date, datetime, time
from pathlib import Path

from .errors import WeiboDownloaderError
from .client import WeiboClient
from .cookies import load_cookie_file
from .downloader import WeiboImageDownloader
from .paths import default_download_dir
from .parser import BEIJING_TZ
from .state import DownloadState

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("微博博主正文原图下载器")
    print("日期与微博时间均按北京时间处理。")

    try:
        profile = _prompt_required("博主主页 URL 或 UID: ")
        start_date = _prompt_date("开始日期 (YYYY-MM-DD): ")
        end_date = _prompt_date("结束日期 (YYYY-MM-DD): ")
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        cookie_path = _prompt_cookie_path()
        output_dir = _prompt_output_dir()

        parsed_cookies = load_cookie_file(cookie_path)
        client = WeiboClient(parsed_cookies.jar)
        print(f"已读取 {parsed_cookies.count} 个 Cookie（{parsed_cookies.format}）。")

        uid = client.resolve_uid(profile)
        print(f"已解析博主 UID: {uid}")

        start = datetime.combine(start_date, time.min, tzinfo=BEIJING_TZ)
        end = datetime.combine(end_date, time.max, tzinfo=BEIJING_TZ)
        print("正在读取微博列表...")
        images = list(client.iter_timeline_images(uid, start, end))
        images.sort(
            key=lambda item: (item.published_at, item.post_id, item.image_index)
        )
        print(f"日期范围内找到 {len(images)} 张正文图片。")
        if not images:
            return 0

        state = DownloadState.load(output_dir)
        downloader = WeiboImageDownloader(client, output_dir, state)
        stats = downloader.download_all(uid, images)
        print(
            "完成："
            f"下载 {stats.downloaded}，跳过 {stats.skipped}，"
            f"降级 {stats.degraded}，失败 {stats.failed}。"
        )
        if stats.failed:
            print(f"失败详情已写入: {output_dir / '.weibo_photo_failed.jsonl'}")
            return 1
        return 0
    except KeyboardInterrupt:
        print("\n任务已取消。")
        return 130
    except (WeiboDownloaderError, ValueError) as exc:
        logger.error("%s", exc)
        return 1


def _prompt_required(prompt: str) -> str:
    while True:
        value = input(prompt).strip().strip('"').strip("'")
        if value:
            return value
        print("输入不能为空。")


def _prompt_date(prompt: str) -> date:
    while True:
        value = input(prompt).strip()
        try:
            return date.fromisoformat(value)
        except ValueError:
            print("日期格式无效，请使用 YYYY-MM-DD。")


def _prompt_cookie_path() -> Path:
    while True:
        value = _prompt_required("Cookie 文件路径: ")
        path = Path(value).expanduser()
        if path.is_file():
            return path
        print(f"找不到 Cookie 文件: {path}")


def _prompt_output_dir() -> Path:
    default = default_download_dir()
    value = input(f"下载目录 [{default}]: ").strip().strip('"').strip("'")
    return Path(value).expanduser() if value else default
