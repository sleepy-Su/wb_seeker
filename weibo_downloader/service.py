from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from .client import WeiboClient
from .cookies import load_cookie_file
from .downloader import DownloadStats, WeiboImageDownloader
from .errors import OperationCancelled
from .parser import BEIJING_TZ
from .state import DownloadState

LogCallback = Callable[[str], None]
CancelEvent = Any


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    profile: str
    start_date: date
    end_date: date
    cookie_path: Path
    output_dir: Path

    def __post_init__(self) -> None:
        if not self.profile.strip():
            raise ValueError("博主主页 URL 或 UID 不能为空")
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")


@dataclass(slots=True)
class DownloadRunResult:
    uid: str
    images_found: int
    stats: DownloadStats | None = None


def run_download(
    request: DownloadRequest,
    *,
    log: LogCallback | None = None,
    cancel_event: CancelEvent | None = None,
) -> DownloadRunResult:
    log_message = log or (lambda _message: None)
    _raise_if_cancelled(cancel_event)

    log_message("正在读取 Cookie...")
    parsed_cookies = load_cookie_file(request.cookie_path)
    log_message(f"已读取 {parsed_cookies.count} 个 Cookie（{parsed_cookies.format}）。")

    client = WeiboClient(parsed_cookies.jar)
    _raise_if_cancelled(cancel_event)

    log_message("正在解析博主 UID...")
    uid = client.resolve_uid(request.profile)
    log_message(f"已解析博主 UID: {uid}")

    start = datetime.combine(request.start_date, time.min, tzinfo=BEIJING_TZ)
    end = datetime.combine(request.end_date, time.max, tzinfo=BEIJING_TZ)
    log_message("正在读取微博列表...")
    images = list(
        client.iter_timeline_images(uid, start, end, cancel_event=cancel_event)
    )
    images.sort(key=lambda item: (item.published_at, item.post_id, item.image_index))
    log_message(f"日期范围内找到 {len(images)} 张正文图片。")
    _raise_if_cancelled(cancel_event)

    if not images:
        return DownloadRunResult(uid=uid, images_found=0)

    state = DownloadState.load(request.output_dir)
    downloader = WeiboImageDownloader(client, request.output_dir, state)
    stats = downloader.download_all(uid, images, cancel_event=cancel_event)
    return DownloadRunResult(uid=uid, images_found=len(images), stats=stats)


def _raise_if_cancelled(cancel_event: CancelEvent | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled("任务已取消")
