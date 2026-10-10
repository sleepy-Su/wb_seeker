import pytest

from weibo_downloader.cookies import parse_cookie_text
from weibo_downloader.errors import CookieError


def test_parse_netscape_cookies_with_httponly_prefix() -> None:
    text = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.weibo.com\tTRUE\t/\tTRUE\t1893456000\tSUB\tsecret-sub\n"
        ".weibo.com\tTRUE\t/\tFALSE\t0\tSUBP\tsecret-subp\n"
    )

    parsed = parse_cookie_text(text)

    assert parsed.format == "netscape"
    assert parsed.count == 2
    assert parsed.jar.get("SUB", domain=".weibo.com") == "secret-sub"
    assert parsed.jar.get("SUBP", domain=".weibo.com") == "secret-subp"
    subp = next(cookie for cookie in parsed.jar if cookie.name == "SUBP")
    assert subp.expires is None


def test_parse_raw_devtools_cookie_header() -> None:
    parsed = parse_cookie_text("Cookie: SUB=abc; SUBP=def; XSRF-TOKEN=ghi")

    assert parsed.format == "raw-header"
    assert parsed.count == 3
    assert parsed.jar.get("SUB", domain=".weibo.com") == "abc"


def test_empty_cookie_file_is_rejected() -> None:
    with pytest.raises(CookieError):
        parse_cookie_text("   \n")
