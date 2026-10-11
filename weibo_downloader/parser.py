from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .models import ImageCandidate, PostImage

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

_IMAGE_SIZE_SEGMENTS = {
    "thumbnail",
    "small",
    "square",
    "bmiddle",
    "mw690",
    "mw1024",
    "mw2000",
    "orj720",
    "orj960",
    "orj1080",
    "orj1440",
    "orj2048",
    "orj360",
    "orj480",
    "wap180",
    "wap360",
    "thumb150",
    "thumb300",
}

_PROFILE_UID_PATTERNS = (
    re.compile(r"^/u/(?P<uid>\d+)(?:/.*)?$", re.IGNORECASE),
    re.compile(r"^/profile/(?P<uid>\d+)(?:/.*)?$", re.IGNORECASE),
    re.compile(r"^/(?P<uid>\d+)(?:/.*)?$"),
)


class CreatedAtError(ValueError):
    pass


def parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=BEIJING_TZ)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise CreatedAtError("empty created_at value")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
            except ValueError as exc:
                raise CreatedAtError(f"unsupported created_at value: {text!r}") from exc
    else:
        raise CreatedAtError(f"unsupported created_at type: {type(value).__name__}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def parse_profile_uid(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return text

    if "://" not in text:
        text = f"https://{text}"
    parsed = urlsplit(text)
    host = (parsed.hostname or "").lower()
    if not (host == "weibo.com" or host.endswith(".weibo.com")) and not (
        host == "weibo.cn" or host.endswith(".weibo.cn")
    ):
        return None

    for pattern in _PROFILE_UID_PATTERNS:
        match = pattern.match(parsed.path or "/")
        if match:
            return match.group("uid")
    return None


def normalize_image_url(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    elif text.startswith("/"):
        text = urljoin("https://weibo.com", text)

    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    segments = parsed.path.lstrip("/").split("/")
    for index, segment in enumerate(segments[:3]):
        if segment.lower() in _IMAGE_SIZE_SEGMENTS:
            segments[index] = "large"
            break

    path = "/" + "/".join(segments) if segments else parsed.path
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def is_original_image_url(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith("//"):
        text = f"https:{text}"
    elif text.startswith("/"):
        text = urljoin("https://weibo.com", text)

    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    segments = parsed.path.lstrip("/").split("/")
    return any(segment.lower() in {"large", "original"} for segment in segments[:3])


def _value_from_node(node: Any) -> tuple[str | None, int | None, int | None]:
    if isinstance(node, str):
        return node, None, None
    if not isinstance(node, Mapping):
        return None, None, None

    url = node.get("url") or node.get("pic") or node.get("src")
    width = _positive_int(node.get("width"))
    height = _positive_int(node.get("height"))
    return str(url) if url else None, width, height


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def extract_candidates(info: Mapping[str, Any]) -> tuple[ImageCandidate, ...]:
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()

    # Weibo's "original" field can point to orj1080, while "largest" is the
    # full-size image exposed by the web viewer's original-image action.
    for quality, key in (
        ("largest", "largest"),
        ("original", "original"),
        ("large", "large"),
        ("mw2000", "mw2000"),
    ):
        raw_url, width, height = _value_from_node(info.get(key))
        url = normalize_image_url(raw_url) if raw_url else None
        if url and url not in seen:
            actual_quality = "original" if is_original_image_url(url) else quality
            candidates.append(
                ImageCandidate(url=url, quality=actual_quality, width=width, height=height)
            )
            seen.add(url)

    for key in ("url", "bmiddle", "thumbnail", "small"):
        raw_url, width, height = _value_from_node(info.get(key))
        url = normalize_image_url(raw_url) if raw_url else None
        if url and url not in seen:
            actual_quality = "original" if is_original_image_url(url) else "large-normalized"
            candidates.append(
                ImageCandidate(url=url, quality=actual_quality, width=width, height=height)
            )
            seen.add(url)
            break

    return tuple(candidates)


def _find_pic_info(pic_infos: Any, pic_id: str | None) -> Mapping[str, Any] | None:
    if isinstance(pic_infos, Mapping):
        if pic_id and isinstance(pic_infos.get(pic_id), Mapping):
            return pic_infos[pic_id]
        if not pic_id and len(pic_infos) == 1:
            first = next(iter(pic_infos.values()))
            return first if isinstance(first, Mapping) else None
    if isinstance(pic_infos, Iterable) and not isinstance(pic_infos, (str, bytes)):
        for item in pic_infos:
            if isinstance(item, Mapping) and (not pic_id or str(item.get("pid") or item.get("pic_id")) == pic_id):
                return item
    return None


def extract_post_images(mblog: Mapping[str, Any]) -> tuple[PostImage, ...]:
    if mblog.get("retweeted_status"):
        return ()

    page_info = mblog.get("page_info")
    is_video = isinstance(page_info, Mapping) and str(
        page_info.get("object_type") or page_info.get("type") or ""
    ).lower() == "video"
    if is_video and not mblog.get("pics"):
        return ()

    post_id_value = mblog.get("idstr") or mblog.get("id")
    if not post_id_value:
        return ()
    post_id = str(post_id_value)

    try:
        published_at = parse_created_at(mblog.get("created_at"))
    except CreatedAtError:
        return ()

    pic_infos = mblog.get("pic_infos")
    pics = mblog.get("pics")
    sources: list[Mapping[str, Any]] = []

    if isinstance(pics, list) and pics:
        for index, pic in enumerate(pics, start=1):
            if not isinstance(pic, Mapping):
                continue
            pic_id = str(pic.get("pid") or pic.get("pic_id") or "") or None
            info = _find_pic_info(pic_infos, pic_id)
            merged: dict[str, Any] = dict(pic)
            if info:
                merged.update(info)
            candidates = extract_candidates(merged)
            if not candidates:
                candidates = extract_candidates(pic)
            if candidates:
                sources.append({"index": index, "candidates": candidates})
    elif isinstance(pic_infos, Mapping) and pic_infos:
        for index, info in enumerate(pic_infos.values(), start=1):
            if not isinstance(info, Mapping):
                continue
            candidates = extract_candidates(info)
            if candidates:
                sources.append({"index": index, "candidates": candidates})
    elif isinstance(pic_infos, Iterable) and not isinstance(pic_infos, (str, bytes)):
        for index, info in enumerate(pic_infos, start=1):
            if not isinstance(info, Mapping):
                continue
            candidates = extract_candidates(info)
            if candidates:
                sources.append({"index": index, "candidates": candidates})

    return tuple(
        PostImage(
            post_id=post_id,
            published_at=published_at,
            image_index=int(source["index"]),
            candidates=tuple(source["candidates"]),
        )
        for source in sources
    )


def extract_timeline_mblogs(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    mblogs = data.get("list")
    if not isinstance(mblogs, list):
        return []
    return [item for item in mblogs if isinstance(item, Mapping)]
