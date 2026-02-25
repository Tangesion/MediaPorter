import re
from typing import Iterable
from urllib.parse import urlparse

from .models import DownloadTask

URL_PATTERN = re.compile(r"https?://[^\s,]+", re.IGNORECASE)
BILIBILI_PATH_PREFIXES = (
    "/video/",
    "/bangumi/play/",
    "/bangumi/media/",
    "/festival/",
    "/cheese/play/",
    "/medialist/play/",
    "/list/",
    "/s/video/",
    "/s/bangumi/",
    "/anime/",
    "/movie/",
    "/ep",
    "/ss",
)
LEADING_TRIM_CHARS = "\"'([{<\u3010\u300a\u300c\u300e"
TRAILING_TRIM_CHARS = "\"').,!?;:]>\u3011\u300b\u300d\u300f\uff0c\u3002\uff01\uff1f\uff1b\uff1a"


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    normalized_text = _normalize_input_text(text)
    return [_normalize_url_candidate(candidate) for candidate in URL_PATTERN.findall(normalized_text)]


def is_supported_url(url: str) -> bool:
    normalized = _normalize_url_candidate(url)
    parsed = urlparse(normalized)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "b23.tv":
        return True

    if not host.endswith("bilibili.com"):
        return False

    path = parsed.path.lower()
    return any(path.startswith(prefix) for prefix in BILIBILI_PATH_PREFIXES)


def filter_supported_urls(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    valid_urls: list[str] = []
    for raw_url in urls:
        url = _normalize_url_candidate(raw_url)
        if not url or url in seen:
            continue
        if is_supported_url(url):
            valid_urls.append(url)
            seen.add(url)
    return valid_urls


def diagnose_urls(text: str) -> tuple[list[str], list[str]]:
    extracted = extract_urls(text)
    diagnostics: list[str] = []
    valid_urls: list[str] = []

    if not extracted:
        diagnostics.append("No URL pattern found in input.")
        return valid_urls, diagnostics

    seen: set[str] = set()
    for raw_url in extracted:
        url = _normalize_url_candidate(raw_url)
        if not url:
            diagnostics.append("Ignored an empty URL candidate after trimming.")
            continue
        if url in seen:
            diagnostics.append(f"Duplicate ignored: {url}")
            continue
        seen.add(url)

        reason = _unsupported_reason(url)
        if reason:
            diagnostics.append(f"Unsupported: {url} ({reason})")
            continue
        valid_urls.append(url)

    if not valid_urls:
        diagnostics.append("No supported Bilibili URL remained after filtering.")
    if not diagnostics and not valid_urls:
        diagnostics.append("Unknown parser state. Please copy the URL directly from browser address bar.")
    return valid_urls, diagnostics


def parse_download_entries(text: str) -> tuple[list[DownloadTask], list[str]]:
    if not text:
        return [], ["No input."]

    normalized = _normalize_input_text(text)
    tasks: list[DownloadTask] = []
    diagnostics: list[str] = []
    seen: set[str] = set()

    for lineno, raw_line in enumerate(normalized.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        left, right = (line.split("||", 1) + [""])[:2] if "||" in line else (line, "")
        candidates = extract_urls(left)
        if not candidates:
            diagnostics.append(f"Line {lineno}: no URL found.")
            continue

        url = _normalize_url_candidate(candidates[0])
        if url in seen:
            diagnostics.append(f"Line {lineno}: duplicate ignored ({url}).")
            continue
        reason = _unsupported_reason(url)
        if reason:
            diagnostics.append(f"Line {lineno}: unsupported URL ({reason}).")
            continue

        filename = _normalize_filename_candidate(right)
        tasks.append(DownloadTask(url=url, filename=filename))
        seen.add(url)

    if not tasks:
        diagnostics.append("No valid Bilibili URLs found in line-based parser.")
    return tasks, diagnostics


def _unsupported_reason(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "b23.tv":
        return None
    if not host:
        return "missing host"
    if not host.endswith("bilibili.com"):
        return f"host is not bilibili/b23 ({host})"

    path = parsed.path.lower()
    if any(path.startswith(prefix) for prefix in BILIBILI_PATH_PREFIXES):
        return None
    return f"path not supported ({path or '/'})"


def _normalize_url_candidate(url: str) -> str:
    return url.strip().lstrip(LEADING_TRIM_CHARS).rstrip(TRAILING_TRIM_CHARS)


def _normalize_input_text(text: str) -> str:
    replacements = {
        "\uff1a": ":",
        "\uff0f": "/",
        "\uff0e": ".",
        "\uff1f": "?",
        "\uff06": "&",
    }
    normalized = text
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    return normalized


def _normalize_filename_candidate(raw: str) -> str | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = cleaned.strip("\"\u201c\u201d\u2018\u2019'")
    return cleaned or None
