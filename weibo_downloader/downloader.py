from __future__ import annotations

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import requests
from PIL import Image, UnidentifiedImageError

from .errors import AuthError, DownloadError
from .models import PostImage, state_key
from .parser import BEIJING_TZ
from .state import DownloadState, append_failure

logger = logging.getLogger(__name__)

_FILE_NAME_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<sequence>\d{3,})\.(?:jpg|jpeg|png|webp|gif)$",
    re.IGNORECASE,
)
_PILLOW_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
}


class ImageClient(Protocol):
    def get_image(self, url: str) -> Any: ...


@dataclass(slots=True)
class DownloadStats:
    downloaded: int = 0
    skipped: int = 0
    degraded: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.downloaded + self.skipped + self.failed


@dataclass(slots=True)
class DownloadResult:
    path: Path
    downloaded_url: str
    quality: str


class WeiboImageDownloader:
    def __init__(
        self,
        client: ImageClient,
        output_dir: Path,
        state: DownloadState,
        *,
        image_delay: float = 0.25,
    ) -> None:
        self.client = client
        self.output_dir = output_dir
        self.state = state
        self.image_delay = max(0.0, image_delay)

    def download_all(self, uid: str, images: list[PostImage]) -> DownloadStats:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stats = DownloadStats()
        next_sequences: dict[str, int] = {}

        for image in sorted(
            images,
            key=lambda item: (item.published_at.astimezone(BEIJING_TZ), item.post_id, item.image_index),
        ):
            key = state_key(uid, image.post_id, image.image_index)
            existing = self.state.get(key)
            if existing:
                filename = existing.get("filename")
                existing_path = self.output_dir / filename if isinstance(filename, str) else None
                if existing_path and existing_path.is_file():
                    stats.skipped += 1
                    continue
                self.state.remove(key)

            date_text = image.published_at.astimezone(BEIJING_TZ).date().isoformat()
            sequence = next_sequences.setdefault(
                date_text, next_available_sequence(self.output_dir, date_text)
            )
            try:
                result = self._download_one(uid, image, date_text, sequence)
            except AuthError:
                raise
            except DownloadError as exc:
                stats.failed += 1
                append_failure(
                    self.output_dir,
                    {
                        "uid": uid,
                        "post_id": image.post_id,
                        "image_index": image.image_index,
                        "published_date": date_text,
                        "original_url": image.original_url,
                        "error": str(exc),
                    },
                )
                logger.warning(
                    "Failed post %s image %s: %s",
                    image.post_id,
                    image.image_index,
                    exc,
                )
                continue

            next_sequences[date_text] = sequence + 1
            stats.downloaded += 1
            if result.quality != "original":
                stats.degraded += 1
            logger.info(
                "Saved %s (%s)",
                result.path.name,
                "original" if result.quality == "original" else f"fallback: {result.quality}",
            )
            if self.image_delay:
                time.sleep(self.image_delay)

        return stats

    def _download_one(
        self,
        uid: str,
        image: PostImage,
        date_text: str,
        sequence: int,
    ) -> DownloadResult:
        errors: list[str] = []
        for candidate in image.candidates:
            temporary_path = self.output_dir / (
                f".{date_text}_{sequence:03d}_{uuid.uuid4().hex}.part"
            )
            try:
                response = self.client.get_image(candidate.url)
            except AuthError:
                raise
            except Exception as exc:
                errors.append(f"{candidate.url}: request failed: {exc}")
                continue

            try:
                status = int(getattr(response, "status_code", 0))
                if status in {401, 403}:
                    raise AuthError(
                        f"Image request was rejected with HTTP {status}; export fresh cookies"
                    )
                if status < 200 or status >= 300:
                    errors.append(f"{candidate.url}: HTTP {status}")
                    continue

                content_type = str(getattr(response, "headers", {}).get("Content-Type", ""))
                if content_type and not content_type.lower().startswith("image/"):
                    errors.append(f"{candidate.url}: unexpected content type {content_type!r}")
                    continue

                with temporary_path.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            stream.write(chunk)

                image_format = _verify_image(temporary_path)
                extension = _PILLOW_EXTENSIONS[image_format]
                final_path = self.output_dir / f"{date_text}_{sequence:03d}{extension}"
                if final_path.exists():
                    errors.append(f"{candidate.url}: destination already exists: {final_path.name}")
                    continue
                os.replace(temporary_path, final_path)
                self.state.mark_completed(
                    state_key(uid, image.post_id, image.image_index),
                    {
                        "filename": final_path.name,
                        "post_id": image.post_id,
                        "image_index": image.image_index,
                        "published_at": image.published_at.isoformat(),
                        "original_url": image.original_url,
                        "downloaded_url": candidate.url,
                        "quality": candidate.quality,
                        "fallback": candidate.quality != "original",
                    },
                )
                return DownloadResult(
                    path=final_path,
                    downloaded_url=candidate.url,
                    quality=candidate.quality,
                )
            except AuthError:
                raise
            except (
                OSError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
                KeyError,
                ValueError,
                requests.RequestException,
            ) as exc:
                errors.append(f"{candidate.url}: invalid image or write failure: {exc}")
            finally:
                try:
                    cast_response = response
                    cast_response.close()
                except Exception:
                    pass
                temporary_path.unlink(missing_ok=True)

        detail = "; ".join(errors) if errors else "no image candidates"
        raise DownloadError(detail)


def next_available_sequence(output_dir: Path, date_text: str) -> int:
    highest = 0
    try:
        entries = output_dir.iterdir()
    except OSError:
        return 1
    for path in entries:
        match = _FILE_NAME_PATTERN.match(path.name)
        if match and match.group("date") == date_text:
            highest = max(highest, int(match.group("sequence")))
    return highest + 1


def _verify_image(path: Path) -> str:
    with Image.open(path) as image:
        image.verify()
        image_format = (image.format or "").upper()
    if image_format not in _PILLOW_EXTENSIONS:
        raise UnidentifiedImageError(f"unsupported image format: {image_format or 'unknown'}")
    return image_format
