from pathlib import Path

from mediaporter_app.downloader import AudioDownloader


def download_audio(video_url: str, output_dir: str = "downloads") -> bool:
    """Backwards-compatible wrapper for legacy CLI callers."""
    downloader = AudioDownloader(output_dir=Path(output_dir))
    result = downloader.download(video_url)
    return result.success
