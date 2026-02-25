from dataclasses import dataclass
from typing import Literal, Optional

DownloadMode = Literal["audio", "video"]
CookieSource = Literal["none", "browser", "file"]
BrowserName = Literal["chrome", "edge"]
VideoQuality = Literal["auto", "1080", "720", "480"]


@dataclass(slots=True)
class DownloadResult:
    url: str
    success: bool
    message: str
    mode: DownloadMode = "audio"
    output_path: Optional[str] = None


@dataclass(slots=True)
class ProgressUpdate:
    percent: float
    message: str


@dataclass(slots=True)
class DownloadTask:
    url: str
    filename: Optional[str] = None
