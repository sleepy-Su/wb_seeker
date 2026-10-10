from __future__ import annotations

from dataclasses import dataclass
from http.cookiejar import Cookie
from pathlib import Path

from requests.cookies import RequestsCookieJar

from .errors import CookieError

_NETSCAPE_FIELD_COUNT = 7
_RAW_COOKIE_DOMAIN = ".weibo.com"


@dataclass(slots=True)
class ParsedCookies:
    jar: RequestsCookieJar
    count: int
    format: str


def load_cookie_file(path: str | Path) -> ParsedCookies:
    cookie_path = Path(path).expanduser()
    if not cookie_path.is_file():
        raise CookieError(f"Cookie file does not exist: {cookie_path}")

    try:
        text = cookie_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = cookie_path.read_text(encoding="gb18030")
        except UnicodeDecodeError as exc:
            raise CookieError("Cookie file is neither UTF-8 nor GB18030 text") from exc
    except OSError as exc:
        raise CookieError(f"Unable to read cookie file: {exc}") from exc

    return parse_cookie_text(text)


def parse_cookie_text(text: str) -> ParsedCookies:
    if not text or not text.strip():
        raise CookieError("Cookie file is empty")

    if _looks_like_netscape(text):
        jar = _parse_netscape(text)
        if not jar:
            raise CookieError("No usable cookies found in Netscape cookie file")
        return ParsedCookies(jar=jar, count=len(jar), format="netscape")

    jar = _parse_raw_header(text)
    if not jar:
        raise CookieError(
            "Cookie file is neither Netscape cookies.txt nor a Cookie header string"
        )
    return ParsedCookies(jar=jar, count=len(jar), format="raw-header")


def _looks_like_netscape(text: str) -> bool:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            continue
        if len(line.split("\t")) >= _NETSCAPE_FIELD_COUNT:
            return True
    return False


def _parse_netscape(text: str) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            continue

        fields = line.split("\t")
        if len(fields) < _NETSCAPE_FIELD_COUNT:
            continue

        domain, _include_subdomains, path, secure_text, expires_text, name, value = fields[:7]
        if not domain or not name:
            continue

        try:
            expires = int(expires_text) if expires_text else None
        except ValueError:
            expires = None

        if expires == 0:
            expires = None

        cookie = Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=domain.startswith("."),
            domain_initial_dot=domain.startswith("."),
            path=path or "/",
            path_specified=bool(path),
            secure=secure_text.upper() == "TRUE",
            expires=expires,
            discard=expires is None,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None} if raw_line.startswith("#HttpOnly_") else {},
            rfc2109=False,
        )
        jar.set_cookie(cookie)
    return jar


def _parse_raw_header(text: str) -> RequestsCookieJar:
    header = text.strip()
    if header.lower().startswith("cookie:"):
        header = header.split(":", 1)[1].strip()
    header = header.splitlines()[0].strip()

    jar = RequestsCookieJar()
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        jar.set(
            name,
            value.strip(),
            domain=_RAW_COOKIE_DOMAIN,
            path="/",
            secure=True,
        )
    return jar
