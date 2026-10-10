from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    url: str
    quality: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class PostImage:
    post_id: str
    published_at: datetime
    image_index: int
    candidates: tuple[ImageCandidate, ...]

    @property
    def original_url(self) -> str:
        for candidate in self.candidates:
            if candidate.quality == "original":
                return candidate.url
        return self.candidates[0].url


def state_key(uid: str, post_id: str, image_index: int) -> str:
    return f"{uid}:{post_id}:{image_index}"
