from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QThread, QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QDialog,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, APP_ORG, APP_VERSION, DEFAULT_DOWNLOAD_DIR
from .downloader import MediaDownloader
from .qr_login import BilibiliQrLoginClient, QrLoginError
from .models import DownloadTask
from .url_parser import diagnose_urls, parse_download_entries
from .worker import DownloadWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: DownloadWorker | None = None
        self.completed_tasks = 0
        self.total_tasks = 0
        self.current_tasks: list[DownloadTask] = []
        self.failed_tasks: list[DownloadTask] = []
        self.active_mode = "audio"
        self.history_entries: list[dict[str, str]] = []
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.ffmpeg_available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        self.install_process: QProcess | None = None
        self._install_log_buffer = ""
        self._install_last_percent = -1
        self._install_last_ratio_text = ""
        self._install_last_output_ts = 0.0
        self._install_stall_warned = False
        self.install_watchdog = QTimer(self)
        self.install_watchdog.setInterval(5000)
        self.install_watchdog.timeout.connect(self._check_install_stall)
        self.qr_login_dialog: QDialog | None = None
        self.qr_login_timer = QTimer(self)
        self.qr_login_timer.setInterval(1800)
        self.qr_login_timer.timeout.connect(self._poll_qr_login)
        self.qr_login_client: BilibiliQrLoginClient | None = None
        self.qr_login_key: str = ""
        self.qr_confirm_url: str | None = None
        self.qr_remaining_seconds = 180
        self.qr_poll_tick = 0
        self._qr_status_label: QLabel | None = None
        self._qr_countdown_label: QLabel | None = None
        self._qr_image_label: QLabel | None = None

        self._build_ui()
        self._load_settings()
        self._connect_events()

    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(980, 820)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        input_box = QGroupBox("Input URLs")
        input_layout = QVBoxLayout(input_box)
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "One task per line. Format: <url> || <custom file name optional>."
        )
        input_layout.addWidget(self.url_input)

        self.task_editor = QTableWidget(0, 2)
        self.task_editor.setHorizontalHeaderLabels(["Task URL", "Custom File Name"])
        self.task_editor.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_editor.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.task_editor.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.task_editor.setColumnWidth(0, 520)
        self.task_editor.setColumnWidth(1, 220)
        input_layout.addWidget(self.task_editor)

        task_editor_action_layout = QHBoxLayout()
        self.load_tasks_button = QPushButton("Load Tasks From Text")
        self.add_task_row_button = QPushButton("Add Task Row")
        self.remove_task_row_button = QPushButton("Remove Selected Rows")
        task_editor_action_layout.addWidget(self.load_tasks_button)
        task_editor_action_layout.addWidget(self.add_task_row_button)
        task_editor_action_layout.addWidget(self.remove_task_row_button)
        task_editor_action_layout.addStretch()
        input_layout.addLayout(task_editor_action_layout)
        layout.addWidget(input_box)

        output_box = QGroupBox("Output")
        output_layout = QGridLayout(output_box)
        output_layout.addWidget(QLabel("Download folder:"), 0, 0)
        self.output_dir = QLineEdit(str(DEFAULT_DOWNLOAD_DIR))
        output_layout.addWidget(self.output_dir, 0, 1)
        self.browse_button = QPushButton("Browse")
        output_layout.addWidget(self.browse_button, 0, 2)

        output_layout.addWidget(QLabel("Download mode:"), 1, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Audio (MP3 preferred)", "audio")
        self.mode_combo.addItem("Video (MP4 preferred)", "video")
        output_layout.addWidget(self.mode_combo, 1, 1)

        output_layout.addWidget(QLabel("Video quality:"), 2, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Auto (best)", "auto")
        self.quality_combo.addItem("1080p", "1080")
        self.quality_combo.addItem("720p", "720")
        self.quality_combo.addItem("480p", "480")
        output_layout.addWidget(self.quality_combo, 2, 1)

        output_layout.addWidget(QLabel("Retries on failure:"), 3, 0)
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 5)
        self.retry_spin.setValue(1)
        output_layout.addWidget(self.retry_spin, 3, 1)
        layout.addWidget(output_box)

        env_box = QGroupBox("Environment")
        env_layout = QVBoxLayout(env_box)
        self.env_status = QPlainTextEdit()
        self.env_status.setReadOnly(True)
        self.env_status.setMaximumHeight(66)
        env_layout.addWidget(self.env_status)
        self.install_ffmpeg_button = QPushButton("Install FFmpeg (Auto)")
        self.stop_install_button = QPushButton("Stop Installer")
        self.stop_install_button.setEnabled(False)
        env_layout.addWidget(self.install_ffmpeg_button)
        env_layout.addWidget(self.stop_install_button)
        layout.addWidget(env_box)

        login_box = QGroupBox("Login (for VIP/paid content if your account has access)")
        login_layout = QGridLayout(login_box)
        login_layout.addWidget(QLabel("Cookie source:"), 0, 0)
        self.cookie_source_combo = QComboBox()
        self.cookie_source_combo.addItem("No login cookies", "none")
        self.cookie_source_combo.addItem("Read cookies from browser", "browser")
        self.cookie_source_combo.addItem("Use cookie file", "file")
        login_layout.addWidget(self.cookie_source_combo, 0, 1)

        login_layout.addWidget(QLabel("Browser:"), 1, 0)
        self.browser_combo = QComboBox()
        self.browser_combo.addItem("Edge", "edge")
        self.browser_combo.addItem("Chrome", "chrome")
        login_layout.addWidget(self.browser_combo, 1, 1)

        login_layout.addWidget(QLabel("Cookie file:"), 2, 0)
        self.cookie_file_input = QLineEdit("")
        login_layout.addWidget(self.cookie_file_input, 2, 1)
        self.cookie_file_button = QPushButton("Browse")
        login_layout.addWidget(self.cookie_file_button, 2, 2)
        self.open_bilibili_login_button = QPushButton("QR Login Bilibili")
        login_layout.addWidget(self.open_bilibili_login_button, 3, 0)
        self.check_login_button = QPushButton("Check Login/VIP")
        login_layout.addWidget(self.check_login_button, 3, 1)
        layout.addWidget(login_box)

        action_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Download")
        self.diagnose_button = QPushButton("Diagnose Formats")
        self.retry_failed_button = QPushButton("Retry Failed")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.retry_failed_button.setEnabled(False)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.diagnose_button)
        action_layout.addWidget(self.retry_failed_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["URL", "File Name", "Status", "Progress", "Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 330)
        layout.addWidget(self.table)

        detail_box = QGroupBox("Selected Message (copyable)")
        detail_layout = QVBoxLayout(detail_box)
        self.message_detail = QPlainTextEdit()
        self.message_detail.setReadOnly(True)
        self.message_detail.setPlaceholderText("Select a row to view full message here.")
        detail_layout.addWidget(self.message_detail)
        layout.addWidget(detail_box)

        log_box = QGroupBox("Logs")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_box)

        history_box = QGroupBox("Download History")
        history_layout = QVBoxLayout(history_box)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Time", "Mode", "Status", "URL", "Message"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        history_layout.addWidget(self.history_table)
        self.clear_history_button = QPushButton("Clear History")
        history_layout.addWidget(self.clear_history_button)
        layout.addWidget(history_box)

        self._refresh_mode_ui()
        self._refresh_login_ui()
        self._refresh_env_status()

    def _connect_events(self) -> None:
        self.browse_button.clicked.connect(self._pick_directory)
        self.start_button.clicked.connect(self.start_download)
        self.diagnose_button.clicked.connect(self.diagnose_formats)
        self.retry_failed_button.clicked.connect(self.retry_failed_download)
        self.stop_button.clicked.connect(self.stop_download)
        self.cookie_file_button.clicked.connect(self._pick_cookie_file)
        self.cookie_source_combo.currentIndexChanged.connect(self._refresh_login_ui)
        self.mode_combo.currentIndexChanged.connect(self._refresh_mode_ui)
        self.clear_history_button.clicked.connect(self._clear_history)
        self.table.currentCellChanged.connect(self._on_table_current_cell_changed)
        self.install_ffmpeg_button.clicked.connect(self.install_ffmpeg)
        self.stop_install_button.clicked.connect(self.stop_install_ffmpeg)
        self.open_bilibili_login_button.clicked.connect(self.open_bilibili_login)
        self.check_login_button.clicked.connect(self.check_login_status)
        self.load_tasks_button.clicked.connect(self.load_tasks_from_text)
        self.add_task_row_button.clicked.connect(self.add_task_row)
        self.remove_task_row_button.clicked.connect(self.remove_selected_task_rows)

    def _load_settings(self) -> None:
        download_dir = self.settings.value("download_dir", str(DEFAULT_DOWNLOAD_DIR), type=str)
        self.output_dir.setText(download_dir)

        max_retries = self.settings.value("max_retries", 1, type=int)
        self.retry_spin.setValue(max(0, min(5, max_retries)))

        mode = self.settings.value("download_mode", "audio", type=str)
        self._set_combo_by_data(self.mode_combo, mode, "audio")
        quality = self.settings.value("video_quality", "auto", type=str)
        self._set_combo_by_data(self.quality_combo, quality, "auto")

        cookie_source = self.settings.value("cookie_source", "none", type=str)
        self._set_combo_by_data(self.cookie_source_combo, cookie_source, "none")
        browser_name = self.settings.value("browser_name", "edge", type=str)
        self._set_combo_by_data(self.browser_combo, browser_name, "edge")
        cookie_file = self.settings.value("cookie_file", "", type=str)
        self.cookie_file_input.setText(cookie_file)

        history_json = self.settings.value("download_history_json", "[]", type=str)
        try:
            parsed_history = json.loads(history_json)
            if isinstance(parsed_history, list):
                self.history_entries = [
                    entry
                    for entry in parsed_history
                    if isinstance(entry, dict)
                    and all(key in entry for key in ("time", "mode", "status", "url", "message"))
                ]
        except json.JSONDecodeError:
            self.history_entries = []
        self._refresh_history_table()

        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

        self._refresh_mode_ui()
        self._refresh_login_ui()
        self.retry_failed_button.setEnabled(bool(self.failed_tasks))

    def _save_settings(self) -> None:
        self.settings.setValue("download_dir", self.output_dir.text().strip())
        self.settings.setValue("max_retries", self.retry_spin.value())
        self.settings.setValue("download_mode", self.mode_combo.currentData())
        self.settings.setValue("video_quality", self.quality_combo.currentData())
        self.settings.setValue("cookie_source", self.cookie_source_combo.currentData())
        self.settings.setValue("browser_name", self.browser_combo.currentData())
        self.settings.setValue("cookie_file", self.cookie_file_input.text().strip())
        self.settings.setValue("download_history_json", json.dumps(self.history_entries[-300:], ensure_ascii=True))
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming convention
        if self.install_process and self.install_process.state() != QProcess.NotRunning:
            answer = QMessageBox.question(
                self,
                APP_NAME,
                "FFmpeg installation is still running. Stop installation and exit?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._stop_install_process()

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

    def _pick_cookie_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select cookie file",
            self.cookie_file_input.text().strip(),
            "Cookie files (*.txt *.cookies);;All files (*.*)",
        )
        if selected:
            self.cookie_file_input.setText(selected)

    def _refresh_mode_ui(self) -> None:
        is_video = self.mode_combo.currentData() == "video"
        self.quality_combo.setEnabled(is_video)
        self._refresh_env_status()

    def _refresh_login_ui(self) -> None:
        source = self.cookie_source_combo.currentData()
        use_browser = source == "browser"
        use_file = source == "file"
        self.browser_combo.setEnabled(use_browser)
        self.cookie_file_input.setEnabled(use_file)
        self.cookie_file_button.setEnabled(use_file)

    def _refresh_env_status(self) -> None:
        self.ffmpeg_available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        mode = self.mode_combo.currentData()
        if self.ffmpeg_available:
            text = "FFmpeg status: available (ffmpeg + ffprobe found)."
        elif mode == "video":
            text = (
                "FFmpeg status: missing. Video mode can only download streams that already contain audio. "
                "For most Bilibili videos with separate tracks, install ffmpeg to merge audio/video."
            )
        else:
            text = "FFmpeg status: missing. Audio mode still works (source format fallback)."
        self.env_status.setPlainText(text)
        is_installing = bool(self.install_process and self.install_process.state() != QProcess.NotRunning)
        self.install_ffmpeg_button.setEnabled((not self.ffmpeg_available) and (not is_installing))
        self.stop_install_button.setEnabled(is_installing)

    def start_download(self, checked: bool = False) -> None:
        del checked  # Qt clicked(bool) compatibility.
        self._start_download(tasks_override=None)

    def load_tasks_from_text(self, checked: bool = False) -> None:
        del checked
        tasks, diagnostics = parse_download_entries(self.url_input.toPlainText())
        if not tasks:
            detail = "\n".join(diagnostics[:6]) if diagnostics else "No valid tasks found."
            QMessageBox.warning(self, APP_NAME, f"Failed to load tasks.\n\nReason:\n{detail}")
            return
        self._set_task_editor_rows(tasks)
        self._append_log(f"Loaded {len(tasks)} task(s) into task editor.")
        if diagnostics:
            self._append_log("Task load diagnostics: " + " | ".join(diagnostics[:4]))

    def add_task_row(self, checked: bool = False) -> None:
        del checked
        row = self.task_editor.rowCount()
        self.task_editor.insertRow(row)
        self.task_editor.setItem(row, 0, QTableWidgetItem(""))
        self.task_editor.setItem(row, 1, QTableWidgetItem(""))

    def remove_selected_task_rows(self, checked: bool = False) -> None:
        del checked
        selected_rows = sorted({index.row() for index in self.task_editor.selectedIndexes()}, reverse=True)
        for row in selected_rows:
            self.task_editor.removeRow(row)

    def install_ffmpeg(self, checked: bool = False) -> None:
        del checked  # Qt clicked(bool) compatibility.
        if self.ffmpeg_available:
            QMessageBox.information(self, APP_NAME, "FFmpeg is already installed.")
            return
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait until current download tasks finish.")
            return
        if self.install_process and self.install_process.state() != QProcess.NotRunning:
            QMessageBox.information(self, APP_NAME, "FFmpeg installation is already running.")
            return

        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Install FFmpeg now using winget?\nThis may require admin permission and internet access.",
        )
        if answer != QMessageBox.Yes:
            return

        bat_path = self._create_ffmpeg_install_bat()
        started = self._launch_visible_terminal(bat_path)
        if not started:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Failed to open installer terminal window. Please install FFmpeg manually.",
            )
            return

        self._append_log("Opened visible installer terminal window for FFmpeg installation.")
        QMessageBox.information(
            self,
            APP_NAME,
            "Installer opened in a separate terminal window.\n"
            "Please wait for completion there, then restart this app.",
        )
        self._refresh_env_status()

    def _create_ffmpeg_install_bat(self) -> Path:
        bat_path = Path(tempfile.gettempdir()) / "mediaporter_install_ffmpeg.bat"
        script = (
            "@echo off\n"
            "title MediaPorter FFmpeg Installer\n"
            "winget install --id Gyan.FFmpeg -e --source winget --verbose "
            "--accept-package-agreements --accept-source-agreements\n"
            "echo.\n"
            "echo Installation command finished.\n"
            "echo Please close this window and return to MediaPorter.\n"
            "pause\n"
        )
        bat_path.write_text(script, encoding="ascii")
        return bat_path

    def _launch_visible_terminal(self, bat_path: Path) -> bool:
        # Keep this path simple and explicit: directly run the generated .bat.
        try:
            os.startfile(str(bat_path))
            return True
        except Exception:
            return False

    def stop_install_ffmpeg(self, checked: bool = False) -> None:
        del checked
        if not self.install_process or self.install_process.state() == QProcess.NotRunning:
            return
        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Stop the running FFmpeg installer?",
        )
        if answer == QMessageBox.Yes:
            self._stop_install_process()
            self._refresh_env_status()

    def open_bilibili_login(self, checked: bool = False) -> None:
        del checked
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait until current download tasks finish.")
            return

        try:
            import qrcode
        except Exception:
            QMessageBox.warning(
                self,
                APP_NAME,
                "QR module missing. Please run: pip install qrcode[pil]",
            )
            return

        client = BilibiliQrLoginClient(cookie_output_dir=Path.cwd() / ".auth")

        dialog = QDialog(self)
        dialog.setWindowTitle("QR Login Bilibili")
        dialog.resize(380, 480)
        layout = QVBoxLayout(dialog)
        qr_label = QLabel()
        qr_label.setScaledContents(True)
        qr_label.setFixedSize(320, 320)
        qr_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(qr_label, alignment=Qt.AlignCenter)

        status_label = QLabel("Use Bilibili mobile app to scan QR and confirm login.")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)
        countdown_label = QLabel("")
        layout.addWidget(countdown_label)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(cancel_btn)

        self.qr_login_dialog = dialog
        self.qr_login_client = client
        self.qr_login_key = ""
        self.qr_confirm_url = None
        self._qr_image_label = qr_label
        self._qr_status_label = status_label
        self._qr_countdown_label = countdown_label
        self.qr_remaining_seconds = 180
        self.qr_poll_tick = 0

        if not self._refresh_qr_code():
            self.qr_login_dialog = None
            self.qr_login_client = None
            self._qr_image_label = None
            self._qr_status_label = None
            self._qr_countdown_label = None
            return

        self.qr_login_timer.start()

        result = dialog.exec()
        self.qr_login_timer.stop()
        if result == QDialog.Accepted:
            self._finish_qr_login()
        else:
            self._append_log("QR login canceled.")
        self.qr_login_dialog = None
        self.qr_login_client = None
        self._qr_image_label = None
        self._qr_status_label = None
        self._qr_countdown_label = None

    def _poll_qr_login(self) -> None:
        if not self.qr_login_client or not self.qr_login_key or not self.qr_login_dialog:
            self.qr_login_timer.stop()
            return
        self.qr_remaining_seconds -= 1
        self.qr_poll_tick += 1
        if self._qr_countdown_label:
            self._qr_countdown_label.setText(f"QR refresh in {max(0, self.qr_remaining_seconds)}s")
        if self.qr_remaining_seconds <= 0:
            self._refresh_qr_code()
            return
        if self.qr_poll_tick % 2 != 0:
            return
        try:
            status, message, confirm_url = self.qr_login_client.poll(self.qr_login_key)
        except QrLoginError as exc:
            self.qr_login_timer.stop()
            QMessageBox.warning(self, APP_NAME, f"QR poll failed: {exc}")
            self.qr_login_dialog.reject()
            return

        if self._qr_status_label:
            self._qr_status_label.setText(message)
        if status in ("waiting_scan", "waiting_confirm"):
            return
        if status == "success" and confirm_url:
            self.qr_confirm_url = confirm_url
            self.qr_login_timer.stop()
            self.qr_login_dialog.accept()
            return
        if status == "expired":
            self._refresh_qr_code()
            return

        self.qr_login_timer.stop()
        QMessageBox.warning(self, APP_NAME, message)
        self.qr_login_dialog.reject()

    def _refresh_qr_code(self) -> bool:
        if not self.qr_login_client:
            return False
        try:
            import qrcode
            from PIL.ImageQt import ImageQt
            from PySide6.QtGui import QPixmap

            qr_url, qr_key = self.qr_login_client.generate_qr()
            qr_img = qrcode.make(qr_url).convert("RGB")
            qr_pix = QPixmap.fromImage(ImageQt(qr_img))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Failed to refresh QR code: {exc}")
            return False

        self.qr_login_key = qr_key
        self.qr_remaining_seconds = 180
        self.qr_poll_tick = 0
        if self._qr_image_label:
            self._qr_image_label.setPixmap(qr_pix)
        if self._qr_countdown_label:
            self._qr_countdown_label.setText("QR refresh in 180s")
        if self._qr_status_label:
            self._qr_status_label.setText("Use Bilibili mobile app to scan QR and confirm login.")
        self._append_log("QR code refreshed.")
        return True

    def _finish_qr_login(self) -> None:
        if not self.qr_login_client or not self.qr_confirm_url:
            return
        try:
            cookie_path, report = self.qr_login_client.finalize_login(self.qr_confirm_url)
        except QrLoginError as exc:
            QMessageBox.warning(self, APP_NAME, f"Login confirmation failed: {exc}")
            return

        self.cookie_source_combo.setCurrentIndex(self.cookie_source_combo.findData("file"))
        self.cookie_file_input.setText(str(cookie_path))
        self._refresh_login_ui()
        self.message_detail.setPlainText(report)
        self._append_log(f"QR login successful, cookie file saved: {cookie_path}")
        QMessageBox.information(
            self,
            APP_NAME,
            "QR login successful. Switched to cookie-file mode automatically.\n"
            "Login/VIP check will run now.",
        )
        self.check_login_status()

    def check_login_status(self, checked: bool = False) -> None:
        del checked
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait until current download tasks finish.")
            return

        cookie_source = self.cookie_source_combo.currentData()
        browser_name = self.browser_combo.currentData()
        cookie_file = Path(self.cookie_file_input.text().strip()) if self.cookie_file_input.text().strip() else None

        if cookie_source == "file" and cookie_file is None:
            QMessageBox.warning(self, APP_NAME, "Please choose a cookie file first.")
            return

        downloader = MediaDownloader(
            output_dir=Path(self.output_dir.text().strip() or str(DEFAULT_DOWNLOAD_DIR)),
            mode=self.mode_combo.currentData(),
            video_quality=self.quality_combo.currentData(),
            cookie_source=cookie_source,
            browser_name=browser_name,
            cookie_file=cookie_file,
            logger=self._append_log,
        )
        self._append_log("Running login/VIP diagnosis...")
        report = downloader.diagnose_login()
        self.message_detail.setPlainText(report)
        self._append_log("Login/VIP diagnosis completed. See Selected Message panel.")
        QMessageBox.information(self, APP_NAME, "Login/VIP diagnosis completed.")

    def diagnose_formats(self, checked: bool = False) -> None:
        del checked  # Qt clicked(bool) compatibility.
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait until current download tasks finish.")
            return

        urls, diagnostics = diagnose_urls(self.url_input.toPlainText())
        if not urls:
            detail = "\n".join(diagnostics[:6]) if diagnostics else "Input could not be parsed."
            QMessageBox.warning(self, APP_NAME, f"No valid Bilibili URLs found.\n\nReason:\n{detail}")
            return

        output_dir = Path(self.output_dir.text().strip() or str(DEFAULT_DOWNLOAD_DIR))
        mode = self.mode_combo.currentData()
        quality = self.quality_combo.currentData()
        cookie_source = self.cookie_source_combo.currentData()
        browser_name = self.browser_combo.currentData()
        cookie_file = Path(self.cookie_file_input.text().strip()) if self.cookie_file_input.text().strip() else None

        downloader = MediaDownloader(
            output_dir=output_dir,
            mode=mode,
            video_quality=quality,
            cookie_source=cookie_source,
            browser_name=browser_name,
            cookie_file=cookie_file,
            logger=self._append_log,
        )
        url = urls[0]
        self._append_log(f"Running format diagnosis for: {url}")
        report = downloader.diagnose_formats(url)
        self.message_detail.setPlainText(report)
        if len(urls) > 1:
            self._append_log("Format diagnosis uses only the first valid URL in input.")
        self._append_log("Format diagnosis completed. See Selected Message panel.")
        QMessageBox.information(self, APP_NAME, "Format diagnosis completed. Check 'Selected Message' panel.")

    def _start_download(self, tasks_override: list[DownloadTask] | None = None) -> None:
        if self.thread and self.thread.isRunning():
            return

        if tasks_override is None:
            tasks, diagnostics = self._collect_tasks_for_download()
        else:
            tasks = tasks_override
            diagnostics = []

        if not tasks:
            detail = "\n".join(diagnostics[:6]) if diagnostics else "Input could not be parsed."
            QMessageBox.warning(
                self,
                APP_NAME,
                f"No valid Bilibili URLs found.\n\nReason:\n{detail}",
            )
            self._append_log(f"URL validation failed. Details: {detail}")
            return

        output_dir = Path(self.output_dir.text().strip() or str(DEFAULT_DOWNLOAD_DIR))
        max_retries = self.retry_spin.value()
        mode = self.mode_combo.currentData()
        quality = self.quality_combo.currentData()
        cookie_source = self.cookie_source_combo.currentData()
        browser_name = self.browser_combo.currentData()
        cookie_file = Path(self.cookie_file_input.text().strip()) if self.cookie_file_input.text().strip() else None

        if cookie_source == "file" and cookie_file is None:
            QMessageBox.warning(self, APP_NAME, "Please choose a cookie file or switch cookie source.")
            return

        self.active_mode = mode
        self._reset_table(tasks)
        self._set_running_state(True)
        self._append_log(
            "Queue ready. "
            f"{len(tasks)} task(s). mode={mode}, quality={quality}, retries={max_retries}, cookies={cookie_source}."
        )

        self.thread = QThread(self)
        self.worker = DownloadWorker(
            tasks=tasks,
            output_dir=output_dir,
            max_retries=max_retries,
            mode=mode,
            video_quality=quality,
            cookie_source=cookie_source,
            browser_name=browser_name,
            cookie_file=cookie_file,
        )
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

    def _collect_tasks_for_download(self) -> tuple[list[DownloadTask], list[str]]:
        editor_tasks, editor_diagnostics = self._collect_tasks_from_editor()
        if editor_tasks:
            return editor_tasks, editor_diagnostics
        return parse_download_entries(self.url_input.toPlainText())

    def _collect_tasks_from_editor(self) -> tuple[list[DownloadTask], list[str]]:
        lines: list[str] = []
        for row in range(self.task_editor.rowCount()):
            url_item = self.task_editor.item(row, 0)
            name_item = self.task_editor.item(row, 1)
            url = (url_item.text() if url_item else "").strip()
            filename = (name_item.text() if name_item else "").strip()
            if not url:
                continue
            lines.append(f"{url} || {filename}" if filename else url)
        if not lines:
            return [], []
        return parse_download_entries("\n".join(lines))

    def _set_task_editor_rows(self, tasks: list[DownloadTask]) -> None:
        self.task_editor.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            self.task_editor.setItem(row, 0, QTableWidgetItem(task.url))
            self.task_editor.setItem(row, 1, QTableWidgetItem(task.filename or ""))

    def retry_failed_download(self) -> None:
        if not self.failed_tasks:
            QMessageBox.information(self, APP_NAME, "There are no failed tasks to retry.")
            return
        self._start_download(tasks_override=self.failed_tasks.copy())

    def stop_download(self) -> None:
        if self.worker:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def _reset_table(self, tasks: list[DownloadTask]) -> None:
        self.completed_tasks = 0
        self.total_tasks = len(tasks)
        self.current_tasks = tasks
        self.failed_tasks = []
        self.progress.setValue(0)
        self.retry_failed_button.setEnabled(False)

        self.table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            self.table.setItem(row, 0, QTableWidgetItem(task.url))
            self.table.setItem(row, 1, QTableWidgetItem(task.filename or "(auto)"))
            self.table.setItem(row, 2, QTableWidgetItem("Pending"))
            self.table.setItem(row, 3, QTableWidgetItem("0%"))
            self.table.setItem(row, 4, QTableWidgetItem("-"))
        self.message_detail.clear()

    def _set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.diagnose_button.setEnabled(not running)
        self.retry_failed_button.setEnabled(not running and bool(self.failed_tasks))
        self.stop_button.setEnabled(running)
        self.browse_button.setEnabled(not running)
        self.url_input.setReadOnly(running)
        self.task_editor.setEnabled(not running)
        self.load_tasks_button.setEnabled(not running)
        self.add_task_row_button.setEnabled(not running)
        self.remove_task_row_button.setEnabled(not running)
        self.output_dir.setReadOnly(running)
        self.retry_spin.setEnabled(not running)
        self.mode_combo.setEnabled(not running)
        self.quality_combo.setEnabled(not running and self.mode_combo.currentData() == "video")
        self.cookie_source_combo.setEnabled(not running)
        self.browser_combo.setEnabled(not running and self.cookie_source_combo.currentData() == "browser")
        self.cookie_file_input.setReadOnly(running)
        self.cookie_file_button.setEnabled(not running and self.cookie_source_combo.currentData() == "file")
        self.open_bilibili_login_button.setEnabled(not running)
        self.check_login_button.setEnabled(not running)
        self.clear_history_button.setEnabled(not running)
        if running:
            self.install_ffmpeg_button.setEnabled(False)
        else:
            self._refresh_env_status()

    def _on_task_started(self, index: int, total: int, url: str) -> None:
        self.table.item(index, 2).setText(f"Running ({index + 1}/{total})")
        self.table.item(index, 4).setText("Starting...")
        self._append_log(f"[{index + 1}/{total}] {url}")

    def _on_task_retry(self, index: int, retry_no: int, max_retries: int, message: str) -> None:
        self.table.item(index, 2).setText(f"Retrying ({retry_no}/{max_retries})")
        self.table.item(index, 3).setText("0%")
        self.table.item(index, 4).setText(message)

    def _on_task_progress(self, index: int, percent: float, message: str) -> None:
        clipped_percent = max(0.0, min(100.0, percent))
        self.table.item(index, 3).setText(f"{clipped_percent:.1f}%")
        if message:
            self.table.item(index, 4).setText(message)

    def _on_task_finished(self, index: int, success: bool, output_path: str, message: str) -> None:
        self.completed_tasks += 1
        task = self.current_tasks[index] if index < len(self.current_tasks) else DownloadTask(url="")
        task_url = task.url
        self.table.item(index, 2).setText("Done" if success else "Failed")
        self.table.item(index, 3).setText("100.0%" if success else self.table.item(index, 3).text())
        detail = message if not output_path else f"{message} | {output_path}"
        message_item = self.table.item(index, 4)
        message_item.setText(detail)
        message_item.setToolTip(detail)
        self.message_detail.setPlainText(detail)

        if not success and task_url and all(t.url != task_url for t in self.failed_tasks):
            self.failed_tasks.append(task)

        self._append_history(
            url=task_url,
            mode=self.active_mode,
            status="success" if success else "failed",
            message=detail,
        )

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

    def _append_history(self, url: str, mode: str, status: str, message: str) -> None:
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "status": status,
            "url": url,
            "message": message,
        }
        self.history_entries.append(entry)
        self.history_entries = self.history_entries[-300:]
        self._refresh_history_table()

    def _refresh_history_table(self) -> None:
        display_entries = list(reversed(self.history_entries[-100:]))
        self.history_table.setRowCount(len(display_entries))
        for row, entry in enumerate(display_entries):
            self.history_table.setItem(row, 0, QTableWidgetItem(entry["time"]))
            self.history_table.setItem(row, 1, QTableWidgetItem(entry["mode"]))
            self.history_table.setItem(row, 2, QTableWidgetItem(entry["status"]))
            self.history_table.setItem(row, 3, QTableWidgetItem(entry["url"]))
            self.history_table.setItem(row, 4, QTableWidgetItem(entry["message"]))

    def _clear_history(self) -> None:
        self.history_entries = []
        self._refresh_history_table()
        self._save_settings()

    def _on_table_current_cell_changed(
        self,
        current_row: int,
        current_column: int,
        previous_row: int,
        previous_column: int,
    ) -> None:
        del current_column, previous_row, previous_column
        if current_row < 0:
            self.message_detail.clear()
            return
        item = self.table.item(current_row, 4)
        self.message_detail.setPlainText(item.text() if item else "")

    def _on_install_ffmpeg_output(self) -> None:
        if not self.install_process:
            return
        stdout_chunk = bytes(self.install_process.readAllStandardOutput()).decode("utf-8", errors="ignore")
        stderr_chunk = bytes(self.install_process.readAllStandardError()).decode("utf-8", errors="ignore")
        chunk = stdout_chunk + stderr_chunk
        if not chunk:
            return
        self._install_last_output_ts = time.monotonic()
        self._install_stall_warned = False
        self._log_install_progress_from_line(chunk)

        # winget often uses carriage-return redraw; normalize to line breaks.
        normalized = chunk.replace("\r", "\n")
        self._install_log_buffer += normalized
        lines = self._install_log_buffer.split("\n")
        self._install_log_buffer = lines[-1]

        for line in lines[:-1]:
            cleaned = line.strip()
            if cleaned:
                self._append_log(f"[ffmpeg-install] {cleaned}")
            self._log_install_progress_from_line(cleaned)

    def _on_install_ffmpeg_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        del exit_status
        self.install_watchdog.stop()
        if self._install_log_buffer.strip():
            tail = self._install_log_buffer.strip()
            self._append_log(f"[ffmpeg-install] {tail}")
            self._log_install_progress_from_line(tail)
        self._install_log_buffer = ""
        self._install_last_percent = -1
        self._install_last_ratio_text = ""
        self._install_last_output_ts = 0.0
        self._install_stall_warned = False
        self._refresh_env_status()
        if exit_code == 0 and self.ffmpeg_available:
            QMessageBox.information(self, APP_NAME, "FFmpeg installation completed successfully.")
            self._append_log("FFmpeg installation completed successfully.")
        else:
            QMessageBox.warning(
                self,
                APP_NAME,
                "FFmpeg installation did not complete successfully. "
                "Please try manual install: winget install --id Gyan.FFmpeg -e",
            )
            self._append_log("FFmpeg installation failed or FFmpeg still not detected.")
        self.install_process = None

    def _log_install_progress_from_line(self, line: str) -> None:
        if not line:
            return
        matches = re.findall(r"(\d{1,3})\s*%", line)
        if matches:
            percent = int(matches[-1])
            if percent != self._install_last_percent:
                self._install_last_percent = percent
                self._append_log(f"[ffmpeg-install] progress: {percent}%")
            return

        ratio_match = re.search(
            r"([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB)",
            line,
            re.IGNORECASE,
        )
        if not ratio_match:
            return
        current = self._to_mb(float(ratio_match.group(1)), ratio_match.group(2).upper())
        total = self._to_mb(float(ratio_match.group(3)), ratio_match.group(4).upper())
        if total <= 0:
            return
        percent = int((current / total) * 100)
        ratio_text = f"{current:.2f}MB/{total:.2f}MB"
        if percent == self._install_last_percent and ratio_text == self._install_last_ratio_text:
            return
        self._install_last_percent = percent
        self._install_last_ratio_text = ratio_text
        self._append_log(f"[ffmpeg-install] progress: {percent}% ({ratio_text})")

    @staticmethod
    def _to_mb(value: float, unit: str) -> float:
        if unit == "GB":
            return value * 1024
        if unit == "KB":
            return value / 1024
        return value

    def _stop_install_process(self) -> None:
        if not self.install_process or self.install_process.state() == QProcess.NotRunning:
            return
        self.install_watchdog.stop()
        self._append_log("Stopping FFmpeg installer process...")
        self.install_process.terminate()
        if not self.install_process.waitForFinished(3000):
            self.install_process.kill()
            self.install_process.waitForFinished(2000)

    def _check_install_stall(self) -> None:
        if not self.install_process or self.install_process.state() == QProcess.NotRunning:
            self.install_watchdog.stop()
            return
        if self._install_stall_warned:
            return
        idle_seconds = time.monotonic() - self._install_last_output_ts
        if idle_seconds < 45:
            return
        self._install_stall_warned = True
        self._append_log(
            "[ffmpeg-install] no output for 45s, installer may be stuck. "
            "Click 'Stop Installer' and retry, or run manual winget install."
        )

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, target: str, fallback: str) -> None:
        target_index = combo.findData(target)
        combo.setCurrentIndex(target_index if target_index >= 0 else combo.findData(fallback))


def run() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
