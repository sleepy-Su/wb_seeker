from __future__ import annotations

from datetime import datetime, time
from typing import Any

import requests
import pytest
from weibo_downloader.client import WeiboClient
from weibo_downloader.parser import BEIJING_TZ
from weibo_downloader.errors import WeiboAPIError


class StubTimelineClient(WeiboClient):
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        super().__init__(page_delay=0, request_delay=0, max_retries=0)
        self.pages = pages
        self.requested_pages: list[int] = []

    def fetch_timeline_page(self, uid: str, page: int) -> dict[str, Any]:
        self.requested_pages.append(page)
        if page > len(self.pages):
            return {"ok": 1, "data": {"list": []}}
        return self.pages[page - 1]


def _mblog(post_id: str, created_at: str, *, pinned: bool = False) -> dict[str, Any]:
    return {
        "idstr": post_id,
        "created_at": created_at,
        "isTop": 1 if pinned else 0,
        "pic_infos": {
            f"p{post_id}": {"original": {"url": f"//wx1.sinaimg.cn/large/{post_id}.jpg"}}
        },
        "pics": [{"pid": f"p{post_id}"}],
    }


def test_iter_timeline_images_skips_pinned_old_post_and_stops_after_old_page() -> None:
    pinned_old = _mblog("1", "Thu Oct 01 12:00:00 +0800 2026", pinned=True)
    in_range = _mblog("2", "Fri Oct 09 12:00:00 +0800 2026")
    old = _mblog("3", "Tue Oct 06 12:00:00 +0800 2026")
    client = StubTimelineClient(
        [
            {"ok": 1, "data": {"list": [pinned_old, in_range]}},
            {"ok": 1, "data": {"list": [old]}},
        ]
    )
    start = datetime(2026, 10, 9, 0, 0, tzinfo=BEIJING_TZ)
    end = datetime.combine(start.date(), time.max, tzinfo=BEIJING_TZ)

    images = list(client.iter_timeline_images("123", start, end))

    assert [image.post_id for image in images] == ["2"]
    assert client.requested_pages == [1, 2]


def test_iter_timeline_images_deduplicates_repeated_posts() -> None:
    first = _mblog("2", "Fri Oct 09 12:00:00 +0800 2026")
    second = _mblog("3", "Fri Oct 09 13:00:00 +0800 2026")
    client = StubTimelineClient(
        [
            {"ok": 1, "data": {"list": [first, second]}},
            {"ok": 1, "data": {"list": [first, second]}},
        ]
    )
    start = datetime(2026, 10, 9, 0, 0, tzinfo=BEIJING_TZ)
    end = datetime.combine(start.date(), time.max, tzinfo=BEIJING_TZ)

    images = list(client.iter_timeline_images("123", start, end))

    assert [image.post_id for image in images] == ["2", "3"]
    assert client.requested_pages == [1, 2]


class RetryResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {}
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def json(self) -> dict[str, Any]:
        return self.payload


class RetrySession:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses
        self.headers: dict[str, str] = {}
        self.timeouts: list[Any] = []

    def request(self, method: str, url: str, **kwargs: Any) -> RetryResponse:
        self.timeouts.append(kwargs["timeout"])
        status = self.statuses.pop(0)
        return RetryResponse(status)


def test_request_retries_with_the_same_custom_timeout(monkeypatch: Any) -> None:
    monkeypatch.setattr("weibo_downloader.client.time.sleep", lambda _seconds: None)
    session = RetrySession([500, 200])
    client = WeiboClient(session=session, request_delay=0, max_retries=1)

    response = client._request("GET", "https://example.test/image", timeout=(1.0, 2.0))

    assert response.status_code == 200
    assert session.timeouts == [(1.0, 2.0), (1.0, 2.0)]


def test_fetch_timeline_raises_domain_error_after_network_failure(monkeypatch: Any) -> None:
    client = WeiboClient(page_delay=0, request_delay=0, max_retries=0)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(client, "_request", fail)

    with pytest.raises(WeiboAPIError):
        client.fetch_timeline_page("123", 1)
