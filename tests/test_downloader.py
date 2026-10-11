from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
import requests
from PIL import Image

from weibo_downloader.downloader import WeiboImageDownloader, next_available_sequence
from weibo_downloader.errors import OperationCancelled
from weibo_downloader.models import ImageCandidate, PostImage
from weibo_downloader.parser import BEIJING_TZ
from weibo_downloader.state import DownloadState, FAILED_FILENAME


def _png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (2, 2), color=(20, 40, 60)).save(stream, format="PNG")
    return stream.getvalue()


class FakeResponse:
    def __init__(self, status_code: int, data: bytes = b"", content_type: str = "image/png") -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.data = data
        self.closed = False

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.data]

    def close(self) -> None:
        self.closed = True


class FakeImageClient:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    def get_image(self, url: str) -> FakeResponse:
        self.requested_urls.append(url)
        return self.responses.get(url, FakeResponse(404))


def _post_image(post_id: str, url: str, index: int = 1, hour: int = 12) -> PostImage:
    return PostImage(
        post_id=post_id,
        published_at=datetime(2026, 10, 9, hour, 0, tzinfo=BEIJING_TZ),
        image_index=index,
        candidates=(
            ImageCandidate(f"{url}-original", "original"),
            ImageCandidate(url, "large"),
        ),
    )



class BrokenStreamResponse(FakeResponse):
    def iter_content(self, chunk_size: int) -> list[bytes]:
        raise requests.ConnectionError("stream interrupted")


def test_download_uses_fallback_and_records_degraded_source(tmp_path: Path) -> None:
    url = "https://wx1.sinaimg.cn/large/photo.png"
    client = FakeImageClient({url: FakeResponse(200, _png_bytes())})
    state = DownloadState.load(tmp_path)
    downloader = WeiboImageDownloader(client, tmp_path, state, image_delay=0)

    stats = downloader.download_all("123", [_post_image("501", url)])

    assert stats.downloaded == 1
    assert stats.degraded == 1
    assert (tmp_path / "2026-10-09_001.png").is_file()
    record = state.get("123:501:1")
    assert record is not None
    assert record["fallback"] is True
    assert record["quality"] == "large"
    assert record["original_url"] == f"{url}-original"


def test_interrupted_original_stream_falls_back_to_next_candidate(tmp_path: Path) -> None:
    url = "https://wx1.sinaimg.cn/large/photo.png"
    client = FakeImageClient(
        {
            f"{url}-original": BrokenStreamResponse(200, _png_bytes()),
            url: FakeResponse(200, _png_bytes()),
        }
    )
    state = DownloadState.load(tmp_path)
    downloader = WeiboImageDownloader(client, tmp_path, state, image_delay=0)

    stats = downloader.download_all("123", [_post_image("501", url)])

    assert stats.downloaded == 1
    assert stats.degraded == 1
    assert (tmp_path / "2026-10-09_001.png").is_file()


def test_previous_orj1080_download_is_archived_and_replaced_with_original(tmp_path: Path) -> None:
    filename = "2026-10-09_001.png"
    existing_path = tmp_path / filename
    existing_path.write_bytes(_png_bytes())
    state = DownloadState.load(tmp_path)
    state.mark_completed(
        "123:501:1",
        {
            "filename": filename,
            "post_id": "501",
            "image_index": 1,
            "downloaded_url": "https://wx1.sinaimg.cn/orj1080/photo.png",
            "quality": "original",
        },
    )
    original_url = "https://wx1.sinaimg.cn/large/photo.png"
    image = PostImage(
        post_id="501",
        published_at=datetime(2026, 10, 9, 12, 0, tzinfo=BEIJING_TZ),
        image_index=1,
        candidates=(ImageCandidate(original_url, "original"),),
    )
    client = FakeImageClient({original_url: FakeResponse(200, _png_bytes())})

    stats = WeiboImageDownloader(client, tmp_path, state, image_delay=0).download_all(
        "123", [image]
    )

    assert stats.downloaded == 1
    assert stats.skipped == 0
    assert existing_path.is_file()
    assert (tmp_path / ".weibo_lowres_backup" / filename).is_file()
    record = state.get("123:501:1")
    assert record is not None
    assert record["downloaded_url"] == original_url


def test_repeated_run_skips_existing_file_but_missing_file_is_redownloaded(tmp_path: Path) -> None:
    url = "https://wx1.sinaimg.cn/large/photo.png"
    image = _post_image("501", url)
    first_client = FakeImageClient({url: FakeResponse(200, _png_bytes())})
    state = DownloadState.load(tmp_path)
    WeiboImageDownloader(first_client, tmp_path, state, image_delay=0).download_all("123", [image])

    second_client = FakeImageClient({})
    stats = WeiboImageDownloader(second_client, tmp_path, state, image_delay=0).download_all(
        "123", [image]
    )
    assert stats.skipped == 1
    assert second_client.requested_urls == []

    (tmp_path / "2026-10-09_001.png").unlink()
    third_client = FakeImageClient({url: FakeResponse(200, _png_bytes())})
    reloaded_state = DownloadState.load(tmp_path)
    stats = WeiboImageDownloader(third_client, tmp_path, reloaded_state, image_delay=0).download_all(
        "123", [image]
    )
    assert stats.downloaded == 1
    assert (tmp_path / "2026-10-09_001.png").is_file()


def test_same_image_in_different_posts_is_downloaded_twice(tmp_path: Path) -> None:
    url = "https://wx1.sinaimg.cn/large/shared.png"
    client = FakeImageClient(
        {
            url: FakeResponse(200, _png_bytes()),
        }
    )
    state = DownloadState.load(tmp_path)
    downloader = WeiboImageDownloader(client, tmp_path, state, image_delay=0)

    stats = downloader.download_all(
        "123",
        [_post_image("501", url, hour=10), _post_image("502", url, hour=11)],
    )

    assert stats.downloaded == 2
    assert (tmp_path / "2026-10-09_001.png").is_file()
    assert (tmp_path / "2026-10-09_002.png").is_file()


def test_all_candidates_failing_writes_jsonl_and_continues(tmp_path: Path) -> None:
    url = "https://wx1.sinaimg.cn/large/broken.png"
    good_url = "https://wx1.sinaimg.cn/large/good.png"
    client = FakeImageClient({good_url: FakeResponse(200, _png_bytes())})
    state = DownloadState.load(tmp_path)
    downloader = WeiboImageDownloader(client, tmp_path, state, image_delay=0)

    stats = downloader.download_all(
        "123",
        [_post_image("500", url, hour=9), _post_image("501", good_url, hour=10)],
    )

    assert stats.failed == 1
    assert stats.downloaded == 1
    failure_lines = (tmp_path / FAILED_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(failure_lines) == 1
    record = json.loads(failure_lines[0])
    assert record["post_id"] == "500"


class AlreadyCancelled:
    def is_set(self) -> bool:
        return True


def test_download_all_can_be_cancelled_before_start(tmp_path: Path) -> None:
    state = DownloadState.load(tmp_path)
    downloader = WeiboImageDownloader(FakeImageClient({}), tmp_path, state, image_delay=0)

    with pytest.raises(OperationCancelled):
        downloader.download_all("123", [], cancel_event=AlreadyCancelled())


def test_next_available_sequence_reads_existing_flat_files(tmp_path: Path) -> None:
    (tmp_path / "2026-10-09_007.png").write_bytes(_png_bytes())
    (tmp_path / "2026-10-08_099.jpg").write_bytes(_png_bytes())

    assert next_available_sequence(tmp_path, "2026-10-09") == 8
    assert next_available_sequence(tmp_path, "2026-10-10") == 1
