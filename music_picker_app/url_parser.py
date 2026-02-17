import re
from typing import Iterable

URL_PATTERN = re.compile(r"https?://[^\s,]+", re.IGNORECASE)
SUPPORTED_DOMAINS = (
    "bilibili.com/video/",
    "b23.tv",
)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return [candidate.strip() for candidate in URL_PATTERN.findall(text)]


def is_supported_url(url: str) -> bool:
    lowered = url.lower()
    return any(domain in lowered for domain in SUPPORTED_DOMAINS)


def filter_supported_urls(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    valid_urls: list[str] = []
    for raw_url in urls:
        url = raw_url.strip()
        if not url or url in seen:
            continue
        if is_supported_url(url):
            valid_urls.append(url)
            seen.add(url)
    return valid_urls
