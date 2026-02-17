from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import yt_dlp

from .models import DownloadResult, ProgressUpdate

Logger = Callable[[str], None]
ProgressCallback = Callable[[ProgressUpdate], None]


class AudioDownloader:
    def __init__(
        self,
        output_dir: Path,
        logger: Logger | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or (lambda _: None)
        self.ffmpeg_available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    def download(self, url: str, progress_callback: ProgressCallback | None = None) -> DownloadResult:
        progress_callback = progress_callback or (lambda _: None)

        self.logger(f"Preparing: {url}")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(self.output_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._build_progress_hook(progress_callback)],
        }

        if self.ffmpeg_available:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        else:
            self.logger("FFmpeg not found. Audio will be saved in the source format.")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                base_path = Path(ydl.prepare_filename(info))

            output_path = self._resolve_output_path(base_path)
            if output_path:
                return DownloadResult(
                    url=url,
                    success=True,
                    message="Downloaded successfully",
                    output_path=str(output_path),
                )

            return DownloadResult(
                url=url,
                success=True,
                message="Download completed, but output path could not be resolved.",
            )
        except yt_dlp.utils.DownloadError as exc:
            return DownloadResult(
                url=url,
                success=False,
                message=f"Download failed: {exc}",
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return DownloadResult(
                url=url,
                success=False,
                message=f"Unexpected error: {exc}",
            )

    def _resolve_output_path(self, base_path: Path) -> Path | None:
        if self.ffmpeg_available:
            mp3_path = base_path.with_suffix(".mp3")
            if mp3_path.exists():
                return mp3_path

        if base_path.exists():
            return base_path

        # yt-dlp may rename output extension based on stream format.
        matches = list(base_path.parent.glob(f"{base_path.stem}.*"))
        if matches:
            return matches[0]

        return None

    @staticmethod
    def _build_progress_hook(progress_callback: ProgressCallback):
        def hook(status: dict) -> None:
            state = status.get("status")
            if state == "downloading":
                downloaded = status.get("downloaded_bytes", 0)
                total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
                percent = (downloaded / total * 100) if total else 0.0
                message = status.get("_percent_str", "").strip() or "Downloading"
                progress_callback(ProgressUpdate(percent=percent, message=message))
            elif state == "finished":
                progress_callback(ProgressUpdate(percent=100.0, message="Download finished"))

        return hook
