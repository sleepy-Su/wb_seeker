from datetime import datetime

import pytest

from weibo_downloader.parser import (
    BEIJING_TZ,
    CreatedAtError,
    is_original_image_url,
    extract_candidates,
    extract_post_images,
    normalize_image_url,
    parse_created_at,
    parse_profile_uid,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234567890", "1234567890"),
        ("https://weibo.com/u/1234567890", "1234567890"),
        ("https://weibo.com/u/1234567890/home", "1234567890"),
        ("https://weibo.com/profile/1234567890", "1234567890"),
        ("https://m.weibo.cn/u/1234567890", "1234567890"),
        ("weibo.com/1234567890", "1234567890"),
    ],
)
def test_parse_profile_uid(value: str, expected: str) -> None:
    assert parse_profile_uid(value) == expected


def test_parse_profile_uid_returns_none_for_vanity_name() -> None:
    assert parse_profile_uid("https://weibo.com/n/someone") is None


def test_parse_created_at_uses_beijing_timezone() -> None:
    parsed = parse_created_at("Thu Oct 09 14:30:00 +0800 2026")
    assert parsed == datetime(2026, 10, 9, 14, 30, tzinfo=BEIJING_TZ)


def test_parse_created_at_rejects_unknown_text() -> None:
    with pytest.raises(CreatedAtError):
        parse_created_at("not a date")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://wx1.sinaimg.cn/orj1080/photo.jpg", "https://wx1.sinaimg.cn/large/photo.jpg"),
        ("//wx1.sinaimg.cn/orj360/photo.jpg", "https://wx1.sinaimg.cn/large/photo.jpg"),
        ("https://wx1.sinaimg.cn/bmiddle/photo.jpg", "https://wx1.sinaimg.cn/large/photo.jpg"),
        ("https://wx1.sinaimg.cn/large/photo.jpg", "https://wx1.sinaimg.cn/large/photo.jpg"),
    ],
)
def test_normalize_image_url(value: str, expected: str) -> None:
    assert normalize_image_url(value) == expected


def test_is_original_image_url_recognizes_true_original_paths() -> None:
    assert is_original_image_url("https://wx1.sinaimg.cn/large/photo.jpg")
    assert is_original_image_url("https://wx1.sinaimg.cn/original/photo.jpg")
    assert not is_original_image_url("https://wx1.sinaimg.cn/orj1080/photo.jpg")


def test_extract_candidates_prefers_original_source() -> None:
    candidates = extract_candidates(
        {
            "original": {"url": "https://wx1.sinaimg.cn/orj1080/photo.jpg"},
            "largest": {"url": "https://wx2.sinaimg.cn/large/photo.jpg"},
            "large": {"url": "https://wx3.sinaimg.cn/orj960/photo.jpg"},
            "url": "https://wx4.sinaimg.cn/orj360/photo.jpg",
        }
    )

    assert [candidate.quality for candidate in candidates] == [
        "original",
        "original",
        "original",
        "original",
    ]
    assert candidates[0].url == "https://wx2.sinaimg.cn/large/photo.jpg"


def test_extract_post_images_preserves_picture_order() -> None:
    mblog = {
        "idstr": "501",
        "created_at": "Fri Oct 09 12:00:00 +0800 2026",
        "pics": [{"pid": "p1"}, {"pid": "p2"}],
        "pic_infos": {
            "p2": {"original": {"url": "//wx2.sinaimg.cn/large/p2.jpg"}},
            "p1": {"original": {"url": "//wx1.sinaimg.cn/large/p1.jpg"}},
        },
    }

    images = extract_post_images(mblog)

    assert [(image.image_index, image.original_url) for image in images] == [
        (1, "https://wx1.sinaimg.cn/large/p1.jpg"),
        (2, "https://wx2.sinaimg.cn/large/p2.jpg"),
    ]


def test_extract_post_images_skips_video_cover_without_attached_pictures() -> None:
    mblog = {
        "idstr": "501",
        "created_at": "Fri Oct 09 12:00:00 +0800 2026",
        "page_info": {"object_type": "video"},
        "pic_infos": {"p1": {"original": {"url": "//wx1.sinaimg.cn/large/cover.jpg"}}},
    }

    assert extract_post_images(mblog) == ()


def test_extract_post_images_skips_reposts() -> None:
    mblog = {
        "idstr": "501",
        "created_at": "Fri Oct 09 12:00:00 +0800 2026",
        "retweeted_status": {"idstr": "100"},
        "pic_infos": {"p1": {"original": {"url": "//wx1.sinaimg.cn/large/p1.jpg"}}},
    }

    assert extract_post_images(mblog) == ()
