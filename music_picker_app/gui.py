from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, APP_ORG, APP_VERSION, DEFAULT_DOWNLOAD_DIR
from .url_parser import extract_urls, filter_supported_urls
from .worker import DownloadWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: DownloadWorker | None = None
        self.completed_tasks = 0
        self.total_tasks = 0
        self.settings = QSettings(APP_ORG, APP_NAME)

        self._build_ui()
        self._load_settings()
        self._connect_events()

    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(980, 700)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        input_box = QGroupBox("Input URLs")
        input_layout = QVBoxLayout(input_box)
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "Paste one or more Bilibili links here (bilibili.com/video or b23.tv)."
        )
        input_layout.addWidget(self.url_input)
        layout.addWidget(input_box)

        output_box = QGroupBox("Output")
        output_layout = QGridLayout(output_box)
        output_layout.addWidget(QLabel("Download folder:"), 0, 0)
        self.output_dir = QLineEdit(str(DEFAULT_DOWNLOAD_DIR))
        output_layout.addWidget(self.output_dir, 0, 1)

        self.browse_button = QPushButton("Browse")
        output_layout.addWidget(self.browse_button, 0, 2)

        output_layout.addWidget(QLabel("Retries on failure:"), 1, 0)
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 5)
        self.retry_spin.setValue(1)
        output_layout.addWidget(self.retry_spin, 1, 1)
        layout.addWidget(output_box)

        action_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Download")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["URL", "Status", "Progress", "Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        log_box = QGroupBox("Logs")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_box)

    def _connect_events(self) -> None:
        self.browse_button.clicked.connect(self._pick_directory)
        self.start_button.clicked.connect(self.start_download)
        self.stop_button.clicked.connect(self.stop_download)

    def _load_settings(self) -> None:
        download_dir = self.settings.value("download_dir", str(DEFAULT_DOWNLOAD_DIR), type=str)
        self.output_dir.setText(download_dir)

        max_retries = self.settings.value("max_retries", 1, type=int)
        self.retry_spin.setValue(max(0, min(5, max_retries)))

        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _save_settings(self) -> None:
        self.settings.setValue("download_dir", self.output_dir.text().strip())
        self.settings.setValue("max_retries", self.retry_spin.value())
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming convention
        self._save_settings()
        super().closeEvent(event)

    def _pick_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select download folder",
            self.output_dir.text().strip() or str(DEFAULT_DOWNLOAD_DIR),
        )
        if selected:
            self.output_dir.setText(selected)

    def start_download(self) -> None:
        if self.thread and self.thread.isRunning():
            return

        raw_urls = extract_urls(self.url_input.toPlainText())
        urls = filter_supported_urls(raw_urls)

        if not urls:
            QMessageBox.warning(self, APP_NAME, "No valid Bilibili URLs found.")
            return

        output_dir = Path(self.output_dir.text().strip() or str(DEFAULT_DOWNLOAD_DIR))
        max_retries = self.retry_spin.value()
        self._reset_table(urls)
        self._set_running_state(True)
        self._append_log(
            f"Queue ready. {len(urls)} task(s) to process. Retries: {max_retries}."
        )

        self.thread = QThread(self)
        self.worker = DownloadWorker(urls=urls, output_dir=output_dir, max_retries=max_retries)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.task_started.connect(self._on_task_started)
        self.worker.task_retry.connect(self._on_task_retry)
        self.worker.task_progress.connect(self._on_task_progress)
        self.worker.task_finished.connect(self._on_task_finished)
        self.worker.log.connect(self._append_log)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)

        self.thread.start()

    def stop_download(self) -> None:
        if self.worker:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def _reset_table(self, urls: list[str]) -> None:
        self.completed_tasks = 0
        self.total_tasks = len(urls)
        self.progress.setValue(0)

        self.table.setRowCount(len(urls))
        for row, url in enumerate(urls):
            self.table.setItem(row, 0, QTableWidgetItem(url))
            self.table.setItem(row, 1, QTableWidgetItem("Pending"))
            self.table.setItem(row, 2, QTableWidgetItem("0%"))
            self.table.setItem(row, 3, QTableWidgetItem("-"))

    def _set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.browse_button.setEnabled(not running)
        self.url_input.setReadOnly(running)
        self.output_dir.setReadOnly(running)
        self.retry_spin.setEnabled(not running)

    def _on_task_started(self, index: int, total: int, url: str) -> None:
        self.table.item(index, 1).setText(f"Running ({index + 1}/{total})")
        self.table.item(index, 3).setText("Starting...")
        self._append_log(f"[{index + 1}/{total}] {url}")

    def _on_task_retry(self, index: int, retry_no: int, max_retries: int, message: str) -> None:
        self.table.item(index, 1).setText(f"Retrying ({retry_no}/{max_retries})")
        self.table.item(index, 2).setText("0%")
        self.table.item(index, 3).setText(message)

    def _on_task_progress(self, index: int, percent: float, message: str) -> None:
        clipped_percent = max(0.0, min(100.0, percent))
        self.table.item(index, 2).setText(f"{clipped_percent:.1f}%")
        if message:
            self.table.item(index, 3).setText(message)

    def _on_task_finished(self, index: int, success: bool, output_path: str, message: str) -> None:
        self.completed_tasks += 1
        self.table.item(index, 1).setText("Done" if success else "Failed")
        self.table.item(index, 2).setText("100.0%" if success else self.table.item(index, 2).text())

        detail = message if not output_path else f"{message} | {output_path}"
        self.table.item(index, 3).setText(detail)

        overall = int((self.completed_tasks / self.total_tasks) * 100) if self.total_tasks else 0
        self.progress.setValue(overall)

    def _on_all_done(self, success_count: int, failure_count: int) -> None:
        self._append_log(f"Finished. success={success_count}, failure={failure_count}")
        QMessageBox.information(
            self,
            APP_NAME,
            f"All tasks completed.\nSuccess: {success_count}\nFailed: {failure_count}",
        )

    def _on_thread_finished(self) -> None:
        self._set_running_state(False)
        self.worker = None
        self.thread = None
        self._save_settings()

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)


def run() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
