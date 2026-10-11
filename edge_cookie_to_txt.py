from __future__ import annotations

import re
import time
from pathlib import Path


DEFAULT_DOMAIN = ".weibo.com"
HTTP_ONLY_NAMES = {"SUB", "SUBP", "ALF", "SSOLoginState"}


def _extract_cookie_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""

    if "\n" in raw:
        for line in raw.splitlines():
            match = re.match(r"^\s*cookie\s*:\s*(.+)$", line, re.IGNORECASE)
            if match:
                return match.group(1).strip()

    if raw.lower().startswith("cookie:"):
        return raw.split(":", 1)[1].strip()

    curl_match = re.search(
        r"(?:-H|--header)\s+(['\"])\s*cookie\s*:\s*(.*?)\1",
        raw,
        re.IGNORECASE | re.DOTALL,
    )
    if curl_match:
        return curl_match.group(2).strip()

    return raw


def _parse_pairs(cookie_value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for item in cookie_value.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue

        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or name in seen:
            continue

        seen.add(name)
        pairs.append((name, value))

    return pairs


def main() -> None:
    print("Edge -> F12 -> Network -> open a weibo.com request")
    print("Request Headers -> copy the value after 'cookie:'")
    print("Paste it below, then press Enter twice:")
    print()

    lines: list[str] = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line.strip())

    cookie_value = _extract_cookie_value("\n".join(lines))
    pairs = _parse_pairs(cookie_value)

    if not pairs:
        raise SystemExit("No cookies found. Copy the Cookie request header value and try again.")

    expires = int(time.time()) + 30 * 24 * 60 * 60
    output = [
        "# Netscape HTTP Cookie File",
        f"# Generated from an Edge request header at {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    for name, value in pairs:
        domain = f"#HttpOnly_{DEFAULT_DOMAIN}" if name in HTTP_ONLY_NAMES else DEFAULT_DOMAIN
        output.append(f"{domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}")

    output_path = Path(__file__).with_name("cookies.txt")
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8", newline="\n")

    print()
    print(f"Created: {output_path}")
    print(f"Cookies written: {len(pairs)}")
    print("Keep this file private. It contains login credentials.")


if __name__ == "__main__":
    main()
