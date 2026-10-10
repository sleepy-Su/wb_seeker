from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.cookies import RequestsCookieJar

from .errors import AuthError, OperationCancelled, ProfileResolutionError, WeiboAPIError
from .models import PostImage
from .parser import BEIJING_TZ, extract_post_images, extract_timeline_mblogs, parse_created_at

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_AUTH_MESSAGE_WORDS = ("登录", "login", "cookie", "认证", "安全验证")
_UID_PATTERNS = (
    re.compile(r"\$CONFIG\['oid'\]\s*=\s*['\"](?P<uid>\d+)['\"]"),
    re.compile(r"['\"]oid['\"]\s*:\s*['\"](?P<uid>\d+)['\"]"),
    re.compile(r"['\"]uid['\"]\s*:\s*['\"]?(?P<uid>\d{5,})"),
    re.compile(r"['\"]user_id['\"]\s*:\s*['\"]?(?P<uid>\d{5,})"),
)


def _raise_if_cancelled(cancel_event: Any | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled("任务已取消")


class WeiboClient:
    def __init__(
        self,
        cookies: RequestsCookieJar | None = None,
        *,
        session: requests.Session | None = None,
        page_delay: float = 0.8,
        request_delay: float = 0.15,
        max_retries: int = 3,
        timeout: tuple[float, float] = (10.0, 30.0),
    ) -> None:
        self.session = session or requests.Session()
        if cookies is not None:
            self.session.cookies.update(cookies)
        self.page_delay = max(0.0, page_delay)
        self.request_delay = max(0.0, request_delay)
        self.max_retries = max(0, max_retries)
        self.timeout = timeout
        self.session.headers.update(
            {
                "User-Agent": _DEFAULT_USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://weibo.com/",
            }
        )

    def resolve_uid(self, profile: str) -> str:
        from .parser import parse_profile_uid

        parsed_uid = parse_profile_uid(profile)
        if parsed_uid:
            return parsed_uid

        text = profile.strip()
        if not text:
            raise ProfileResolutionError("Profile URL or UID is empty")
        if "://" not in text:
            text = f"https://{text}"

        parsed = urlsplit(text)
        host = (parsed.hostname or "").lower()
        if not (host == "weibo.com" or host.endswith(".weibo.com")):
            raise ProfileResolutionError(
                "Only numeric Weibo UIDs or weibo.com homepage URLs are supported"
            )

        try:
            response = self._request("GET", text, allow_redirects=True)
        except requests.RequestException as exc:
            raise ProfileResolutionError(f"Unable to open profile URL: {exc}") from exc

        self._raise_for_auth(response)
        parsed_uid = parse_profile_uid(response.url)
        if parsed_uid:
            return parsed_uid

        html = response.text
        for pattern in _UID_PATTERNS:
            match = pattern.search(html)
            if match:
                return match.group("uid")
        raise ProfileResolutionError(
            "Could not resolve a numeric UID from the homepage; use the /u/<uid> URL"
        )

    def fetch_timeline_page(self, uid: str, page: int) -> dict[str, Any]:
        try:
            response = self._request(
                "GET",
                "https://weibo.com/ajax/statuses/mymblog",
                params={"uid": uid, "page": page, "feature": 0},
            )
        except requests.RequestException as exc:
            raise WeiboAPIError(f"Unable to load Weibo timeline: {exc}") from exc
        self._raise_for_auth(response)
        if response.status_code >= 400:
            raise WeiboAPIError(
                f"Weibo timeline returned HTTP {response.status_code} after retries"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeiboAPIError("Weibo timeline returned non-JSON content") from exc
        if not isinstance(payload, dict):
            raise WeiboAPIError("Weibo timeline returned an unexpected JSON shape")

        if payload.get("ok") == 0:
            message = str(payload.get("msg") or payload.get("message") or "unknown error")
            if any(word.lower() in message.lower() for word in _AUTH_MESSAGE_WORDS):
                raise AuthError(f"Weibo login check failed: {message}")
            raise WeiboAPIError(f"Weibo timeline API error: {message}")
        return payload

    def iter_timeline_images(
        self,
        uid: str,
        start: datetime,
        end: datetime,
        *,
        max_pages: int = 5000,
        cancel_event: Any | None = None,
    ) -> Iterator[PostImage]:
        start = start.astimezone(BEIJING_TZ)
        end = end.astimezone(BEIJING_TZ)
        seen_post_ids: set[str] = set()
        previous_page_ids: tuple[str, ...] | None = None

        _raise_if_cancelled(cancel_event)
        for page in range(1, max_pages + 1):
            _raise_if_cancelled(cancel_event)
            payload = self.fetch_timeline_page(uid, page)
            mblogs = extract_timeline_mblogs(payload)
            if not mblogs:
                return

            page_ids = tuple(
                str(item.get("idstr") or item.get("id")) for item in mblogs if item.get("idstr") or item.get("id")
            )
            if page_ids and page_ids == previous_page_ids:
                logger.warning("Weibo timeline repeated page %s; stopping pagination", page)
                return
            previous_page_ids = page_ids

            non_pinned_dates: list[datetime] = []
            for mblog in mblogs:
                _raise_if_cancelled(cancel_event)
                post_id_value = mblog.get("idstr") or mblog.get("id")
                if not post_id_value:
                    continue
                post_id = str(post_id_value)
                if post_id in seen_post_ids:
                    continue
                seen_post_ids.add(post_id)

                is_pinned = bool(mblog.get("isTop") or mblog.get("is_top"))
                if mblog.get("retweeted_status"):
                    continue
                try:
                    published_at = parse_created_at(mblog.get("created_at"))
                except ValueError:
                    continue
                if not is_pinned:
                    non_pinned_dates.append(published_at)
                if start <= published_at <= end:
                    yield from extract_post_images(mblog)

            if non_pinned_dates and max(non_pinned_dates) < start:
                return
            if page < max_pages and self.page_delay:
                time.sleep(self.page_delay)

    def get_image(self, url: str) -> requests.Response:
        return self._request("GET", url, stream=True, timeout=(10.0, 60.0))

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.request_delay:
                time.sleep(self.request_delay)
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise

            self._raise_for_auth(response)
            if response.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                response.close()
                time.sleep(min(2**attempt, 8))
                continue
            return response

        if last_error:
            raise last_error
        raise WeiboAPIError("Request failed without a response")

    @staticmethod
    def _raise_for_auth(response: requests.Response) -> None:
        if response.status_code in {401, 403}:
            response.close()
            raise AuthError(
                f"Weibo rejected the request with HTTP {response.status_code}; export fresh cookies"
            )
