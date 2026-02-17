from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .downloader import AudioDownloader
from .models import DownloadResult, ProgressUpdate


class DownloadWorker(QObject):
    task_started = Signal(int, int, str)
    task_retry = Signal(int, int, int, str)
    task_progress = Signal(int, float, str)
    task_finished = Signal(int, bool, str, str)
    log = Signal(str)
    all_done = Signal(int, int)
    finished = Signal()

    def __init__(self, urls: list[str], output_dir: Path, max_retries: int = 0) -> None:
        super().__init__()
        self.urls = urls
        self.output_dir = output_dir
        self.max_retries = max(0, max_retries)
        self._stopped = False

    @Slot()
    def run(self) -> None:
        success_count = 0
        failure_count = 0

        downloader = AudioDownloader(output_dir=self.output_dir, logger=self.log.emit)
        total = len(self.urls)

        for index, url in enumerate(self.urls):
            if self._stopped:
                self.log.emit("Download canceled by user.")
                break

            self.task_started.emit(index, total, url)
            result: DownloadResult | None = None

            for attempt in range(1, self.max_retries + 2):
                if self._stopped:
                    break

                if attempt > 1:
                    retry_no = attempt - 1
                    retry_message = f"Retrying ({retry_no}/{self.max_retries})"
                    self.task_retry.emit(index, retry_no, self.max_retries, retry_message)
                    self.log.emit(f"[{index + 1}/{total}] {retry_message}: {url}")

                result = downloader.download(
                    url,
                    progress_callback=lambda progress, idx=index: self._on_progress(idx, progress),
                )
                if result.success:
                    break

                self.log.emit(f"[{index + 1}/{total}] Attempt {attempt} failed: {result.message}")

            if self._stopped:
                self.log.emit("Download canceled by user.")
                break

            if result is None:
                result = DownloadResult(url=url, success=False, message="Task canceled before completion.")

            if result.success:
                success_count += 1
            else:
                failure_count += 1

            output_path = result.output_path or ""
            self.task_finished.emit(index, result.success, output_path, result.message)

        self.all_done.emit(success_count, failure_count)
        self.finished.emit()

    @Slot()
    def stop(self) -> None:
        self._stopped = True

    def _on_progress(self, index: int, progress: ProgressUpdate) -> None:
        self.task_progress.emit(index, progress.percent, progress.message)
