from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class DownloadResult:
    url: str
    success: bool
    message: str
    output_path: Optional[str] = None


@dataclass(slots=True)
class ProgressUpdate:
    percent: float
    message: str
