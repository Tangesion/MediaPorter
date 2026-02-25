from __future__ import annotations

import shutil
import re
import json
import urllib.request
from pathlib import Path
from typing import Callable

import yt_dlp

from .models import (
    BrowserName,
    CookieSource,
    DownloadMode,
    DownloadResult,
    ProgressUpdate,
    VideoQuality,
)

Logger = Callable[[str], None]
ProgressCallback = Callable[[ProgressUpdate], None]
BILIBILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


class MediaDownloader:
    def __init__(
        self,
        output_dir: Path,
        mode: DownloadMode = "audio",
        video_quality: VideoQuality = "auto",
        cookie_source: CookieSource = "none",
        browser_name: BrowserName = "edge",
        cookie_file: Path | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.video_quality = video_quality
        self.cookie_source = cookie_source
        self.browser_name = browser_name
        self.cookie_file = cookie_file
        self.logger = logger or (lambda _: None)
        self.ffmpeg_available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        self._last_stream_note = ""

    def download(self, url: str, progress_callback: ProgressCallback | None = None) -> DownloadResult:
        progress_callback = progress_callback or (lambda _: None)

        self.logger(f"Preparing ({self.mode}): {url}")
        ydl_opts = self._build_options(progress_callback)
        custom_name = getattr(self, "_runtime_filename", None)
        if custom_name:
            safe_name = self._sanitize_filename(custom_name)
            if safe_name:
                ydl_opts["outtmpl"] = str(self.output_dir / f"{safe_name}.%(ext)s")

        self._apply_preflight_format_selection(url, ydl_opts)

        try:
            self._last_stream_note = ""
            base_path = self._extract_with_options(url, ydl_opts)

            output_path = self._resolve_output_path(base_path)
            if output_path:
                return DownloadResult(
                    url=url,
                    success=True,
                    message=self._build_success_message(),
                    output_path=str(output_path),
                    mode=self.mode,
                )

            return DownloadResult(
                url=url,
                success=True,
                message=f"{self._build_success_message()}, but output path could not be resolved.",
                mode=self.mode,
            )
        except yt_dlp.utils.DownloadError as exc:
            fallback_path, fallback_error = self._try_format_fallback(url, progress_callback, str(exc))
            if fallback_path is not None:
                output_path = self._resolve_output_path(fallback_path)
                return DownloadResult(
                    url=url,
                    success=True,
                    message="Downloaded successfully (fallback format)",
                    output_path=str(output_path) if output_path else None,
                    mode=self.mode,
                )
            return DownloadResult(
                url=url,
                success=False,
                message=self._map_download_error(fallback_error or str(exc)),
                mode=self.mode,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return DownloadResult(
                url=url,
                success=False,
                message=f"Unexpected error: {exc}",
                mode=self.mode,
            )

    def download_with_filename(
        self,
        url: str,
        filename: str | None,
        progress_callback: ProgressCallback | None = None,
    ) -> DownloadResult:
        self._runtime_filename = filename
        try:
            return self.download(url, progress_callback=progress_callback)
        finally:
            self._runtime_filename = None

    def diagnose_formats(self, url: str) -> str:
        probe_opts = self._build_probe_options()
        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            mapped = self._map_download_error(str(exc))
            return f"Format diagnosis failed.\n{mapped}"
        except Exception as exc:  # pragma: no cover - defensive fallback
            return f"Format diagnosis failed with unexpected error: {exc}"

        if not isinstance(info, dict):
            return "Format diagnosis failed: extractor returned invalid metadata."

        formats = info.get("formats")
        if not isinstance(formats, list) or not formats:
            return "Format diagnosis: no formats returned by extractor."

        selected = self._pick_video_format_selector(formats) if self.mode == "video" else self._select_format()
        title = info.get("title", "(unknown title)")
        lines = [
            f"Title: {title}",
            f"Mode: {self.mode}, Quality: {self.video_quality}, FFmpeg: {'yes' if self.ffmpeg_available else 'no'}",
            f"Recommended selector: {selected or '(none)'}",
            f"Total formats: {len(formats)}",
            "",
            "Top formats:",
            self._summarize_formats(formats, limit=20),
        ]
        return "\n".join(lines)

    def diagnose_login(self) -> str:
        if self.cookie_source == "none":
            return "Login diagnosis skipped: cookie source is 'none'."

        probe_opts = self._build_probe_options()
        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                request = urllib.request.Request(BILIBILI_NAV_API, headers={"User-Agent": DEFAULT_UA})
                response = ydl.urlopen(request)
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        except yt_dlp.utils.DownloadError as exc:
            raw = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
            return f"Login diagnosis failed.\n{self._map_download_error(raw)}\nRaw error: {raw}"
        except Exception as exc:  # pragma: no cover - defensive fallback
            return f"Login diagnosis failed with unexpected error: {exc}"

        return self._format_login_report(payload, self.cookie_source)

    def _build_options(self, progress_callback: ProgressCallback) -> dict:
        ydl_opts: dict = {
            "format": self._select_format(),
            "outtmpl": str(self.output_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._build_progress_hook(progress_callback)],
            "merge_output_format": "mp4",
        }

        if self.mode == "audio":
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
        elif not self.ffmpeg_available:
            self.logger("FFmpeg not found. Video may be downloaded in a non-merged/source format.")

        self._inject_login_options(ydl_opts)
        return ydl_opts

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip().strip(".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:150]

    def _extract_with_options(self, url: str, ydl_opts: dict) -> Path:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            self._update_stream_note(info)
            return Path(ydl.prepare_filename(info))

    def _try_format_fallback(
        self,
        url: str,
        progress_callback: ProgressCallback,
        error_text: str,
    ) -> tuple[Path | None, str | None]:
        lowered = error_text.lower()
        if self.mode != "video" or "requested format is not available" not in lowered:
            return None, None

        self.logger("Requested format unavailable. Retrying with fallback format...")
        fallback_opts = self._build_options(progress_callback)
        if self.ffmpeg_available:
            fallback_opts["format"] = "bestvideo+bestaudio/best"
        else:
            # No ffmpeg: only accept video formats that already include audio.
            fallback_opts["format"] = "best[vcodec!=none][acodec!=none]"
        try:
            return self._extract_with_options(url, fallback_opts), None
        except yt_dlp.utils.DownloadError as exc:
            return None, str(exc)

    def _apply_preflight_format_selection(self, url: str, ydl_opts: dict) -> None:
        if self.mode != "video":
            return

        probe_opts = self._build_probe_options()
        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats") if isinstance(info, dict) else None
            if not isinstance(formats, list):
                return

            selected = self._pick_video_format_selector(formats)
            if selected:
                ydl_opts["format"] = selected
                self.logger(f"Preflight selected format: {selected}")
        except Exception:
            # Probe is best-effort only; normal download flow continues.
            return

    def _build_probe_options(self) -> dict:
        probe_opts = self._build_options(lambda _: None)
        probe_opts["skip_download"] = True
        probe_opts["progress_hooks"] = []
        # Do not force a format during probing, otherwise yt-dlp can fail
        # before returning the format list when preferred selector is unavailable.
        probe_opts.pop("format", None)
        probe_opts.pop("postprocessors", None)
        return probe_opts

    def _pick_video_format_selector(self, formats: list[dict]) -> str | None:
        target_height = self._quality_height_limit()
        if self.ffmpeg_available:
            videos = self._filter_video_only_formats(formats)
            audios = self._filter_audio_only_formats(formats)
            videos = self._apply_height_cap(videos, target_height)

            best_video = self._pick_best_by_score(videos, self._video_score)
            best_audio = self._pick_best_by_score(audios, self._audio_score)
            if best_video and best_audio:
                return f"{best_video['format_id']}+{best_audio['format_id']}"

        progressive = self._filter_progressive_formats(formats)
        progressive = self._apply_height_cap(progressive, target_height)
        best_progressive = self._pick_best_by_score(progressive, self._video_score)
        if best_progressive:
            return str(best_progressive["format_id"])
        return None

    def _update_stream_note(self, info: dict) -> None:
        if self.mode != "video":
            return
        req = info.get("requested_formats")
        if isinstance(req, list) and req:
            codecs = {(fmt or {}).get("acodec", "none") for fmt in req}
            has_audio = any(codec not in (None, "none") for codec in codecs)
            if not has_audio and not self.ffmpeg_available:
                self._last_stream_note = "video-only stream (no audio, ffmpeg not installed)"
            return

        acodec = info.get("acodec")
        if acodec in (None, "none") and not self.ffmpeg_available:
            self._last_stream_note = "video-only stream (no audio, ffmpeg not installed)"

    def _build_success_message(self) -> str:
        if self._last_stream_note:
            return f"Downloaded successfully ({self._last_stream_note})"
        return "Downloaded successfully"

    def _quality_height_limit(self) -> int | None:
        if self.video_quality == "1080":
            return 1080
        if self.video_quality == "720":
            return 720
        if self.video_quality == "480":
            return 480
        return None

    @staticmethod
    def _filter_video_only_formats(formats: list[dict]) -> list[dict]:
        return [
            fmt
            for fmt in formats
            if fmt.get("format_id")
            and fmt.get("vcodec") not in (None, "none")
            and fmt.get("acodec") in (None, "none")
        ]

    @staticmethod
    def _filter_audio_only_formats(formats: list[dict]) -> list[dict]:
        return [
            fmt
            for fmt in formats
            if fmt.get("format_id")
            and fmt.get("acodec") not in (None, "none")
            and fmt.get("vcodec") in (None, "none")
        ]

    @staticmethod
    def _filter_progressive_formats(formats: list[dict]) -> list[dict]:
        return [
            fmt
            for fmt in formats
            if fmt.get("format_id")
            and fmt.get("acodec") not in (None, "none")
            and fmt.get("vcodec") not in (None, "none")
        ]

    @staticmethod
    def _apply_height_cap(formats: list[dict], target_height: int | None) -> list[dict]:
        if not formats or target_height is None:
            return formats
        capped = [fmt for fmt in formats if (fmt.get("height") or 0) and (fmt.get("height") or 0) <= target_height]
        return capped or formats

    @staticmethod
    def _pick_best_by_score(formats: list[dict], score_fn: Callable[[dict], tuple]) -> dict | None:
        if not formats:
            return None
        return max(formats, key=score_fn)

    @staticmethod
    def _video_score(fmt: dict) -> tuple:
        height = int(fmt.get("height") or 0)
        fps = int(fmt.get("fps") or 0)
        tbr = float(fmt.get("tbr") or fmt.get("vbr") or 0.0)
        return (height, fps, tbr)

    @staticmethod
    def _audio_score(fmt: dict) -> tuple:
        abr = float(fmt.get("abr") or fmt.get("tbr") or 0.0)
        asr = int(fmt.get("asr") or 0)
        return (abr, asr)

    @staticmethod
    def _summarize_formats(formats: list[dict], limit: int = 20) -> str:
        def sort_key(fmt: dict) -> tuple:
            return (
                int(fmt.get("height") or 0),
                float(fmt.get("tbr") or 0.0),
                str(fmt.get("format_id") or ""),
            )

        sorted_formats = sorted(
            [fmt for fmt in formats if fmt.get("format_id")],
            key=sort_key,
            reverse=True,
        )
        rows: list[str] = []
        for fmt in sorted_formats[: max(1, limit)]:
            fid = str(fmt.get("format_id"))
            ext = str(fmt.get("ext") or "-")
            height = fmt.get("height")
            fps = fmt.get("fps")
            acodec = str(fmt.get("acodec") or "none")
            vcodec = str(fmt.get("vcodec") or "none")
            tbr = fmt.get("tbr")
            quality = f"{height}p" if height else (str(fmt.get("resolution")) if fmt.get("resolution") else "-")
            fps_text = f"{int(fps)}fps" if fps else "-"
            tbr_text = f"{float(tbr):.0f}k" if tbr else "-"
            rows.append(
                f"- id={fid} ext={ext} quality={quality} fps={fps_text} tbr={tbr_text} "
                f"v={vcodec} a={acodec}"
            )
        return "\n".join(rows) if rows else "(none)"

    @staticmethod
    def _format_login_report(payload: dict, cookie_source: CookieSource) -> str:
        if not isinstance(payload, dict):
            return "Login diagnosis failed: invalid response payload."

        code = payload.get("code")
        message = payload.get("message")
        data = payload.get("data") or {}
        if code != 0 or not isinstance(data, dict):
            return (
                "Login diagnosis failed: Bilibili API returned error.\n"
                f"code={code}, message={message}"
            )

        is_login = bool(data.get("isLogin"))
        uname = str(data.get("uname") or "-")
        mid = str(data.get("mid") or "-")
        vip_type = int(data.get("vipType") or 0)
        vip_status = int(data.get("vipStatus") or 0)
        is_vip = vip_type > 0 and vip_status == 1
        vip_label = "active VIP" if is_vip else "not active VIP"

        lines = [
            f"Cookie source: {cookie_source}",
            f"isLogin: {is_login}",
            f"username: {uname}",
            f"mid: {mid}",
            f"vipType: {vip_type}, vipStatus: {vip_status} ({vip_label})",
        ]
        if not is_login:
            lines.append("Result: cookies do not represent a logged-in account.")
        elif is_vip:
            lines.append("Result: login is valid and VIP is active.")
        else:
            lines.append("Result: login is valid, but VIP is not active for this account.")
        return "\n".join(lines)

    def _select_format(self) -> str:
        if self.mode == "video":
            # Without ffmpeg, avoid split streams that require a merge step.
            if not self.ffmpeg_available:
                if self.video_quality == "1080":
                    return "best[height<=1080][vcodec!=none][acodec!=none]"
                if self.video_quality == "720":
                    return "best[height<=720][vcodec!=none][acodec!=none]"
                if self.video_quality == "480":
                    return "best[height<=480][vcodec!=none][acodec!=none]"
                return "best[vcodec!=none][acodec!=none]"
            if self.video_quality == "1080":
                return "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            if self.video_quality == "720":
                return "bestvideo[height<=720]+bestaudio/best[height<=720]"
            if self.video_quality == "480":
                return "bestvideo[height<=480]+bestaudio/best[height<=480]"
            return "bestvideo+bestaudio/best"
        return "bestaudio/best"

    def _inject_login_options(self, ydl_opts: dict) -> None:
        if self.cookie_source == "browser":
            ydl_opts["cookiesfrombrowser"] = (self.browser_name,)
            self.logger(f"Using browser cookies: {self.browser_name}")
            return

        if self.cookie_source == "file":
            if self.cookie_file and self.cookie_file.exists():
                ydl_opts["cookiefile"] = str(self.cookie_file)
                self.logger(f"Using cookie file: {self.cookie_file}")
            else:
                self.logger("Cookie file not found. Continue without login cookies.")

    def _resolve_output_path(self, base_path: Path) -> Path | None:
        if self.mode == "audio" and self.ffmpeg_available:
            mp3_path = base_path.with_suffix(".mp3")
            if mp3_path.exists():
                return mp3_path

        if base_path.exists():
            return base_path

        matches = list(base_path.parent.glob(f"{base_path.stem}.*"))
        if matches:
            return matches[0]

        return None

    def _map_download_error(self, raw_error: str) -> str:
        cleaned_error = re.sub(r"\x1b\[[0-9;]*m", "", raw_error)
        lowered = cleaned_error.lower()
        if "drm" in lowered:
            return "Download failed: DRM-protected content cannot be downloaded by yt-dlp."
        if "ffmpeg is not installed" in lowered:
            return (
                "Download failed: ffmpeg is missing. Install ffmpeg for high-quality merged video, "
                "or keep current setup and the app will fallback to single-stream video."
            )
        if "winerror 10013" in lowered or "access permissions" in lowered:
            return (
                "Download failed: Local network/socket permission denied (WinError 10013). "
                "Please check firewall/proxy/security software."
            )
        if "http error 403" in lowered or "forbidden" in lowered:
            return "Download failed: Access denied (403). Login/VIP permission may be required."
        if "http error 412" in lowered:
            return "Download failed: Request blocked by platform risk control. Retry later or use valid login cookies."
        if "unable to extract" in lowered:
            return "Download failed: The page format may have changed. Try updating yt-dlp."
        if "vip" in lowered or "pay" in lowered or "premium" in lowered:
            return "Download failed: This content likely requires VIP/payment access with a valid logged-in account."
        if "cookie" in lowered or "login" in lowered:
            return "Download failed: Login may be required. Configure browser/file cookies and retry."
        if "decrypt" in lowered or "dpapi" in lowered or "keyring" in lowered:
            return (
                "Download failed: Browser cookies could not be decrypted/read (DPAPI). "
                "Try updating yt-dlp and run app under your normal user session."
            )
        if "could not copy chrome cookie database" in lowered or "permission denied" in lowered:
            return (
                "Download failed: Browser cookie database is locked or inaccessible. "
                "Close browser completely and retry."
            )
        if "geo" in lowered or "region" in lowered:
            return "Download failed: Region-locked content is not available in your current area."
        if "requested format is not available" in lowered:
            if not self.ffmpeg_available and self.mode == "video":
                return (
                    "Download failed: This video likely provides separate video/audio streams. "
                    "Install ffmpeg to merge tracks, or switch to Audio mode."
                )
            return (
                "Download failed: Requested quality/format is unavailable. "
                f"Try video quality Auto or login cookies for higher tiers. Raw error: {cleaned_error}"
            )
        return f"Download failed: {cleaned_error}"

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


class AudioDownloader(MediaDownloader):
    def __init__(self, output_dir: Path, logger: Logger | None = None) -> None:
        super().__init__(output_dir=output_dir, mode="audio", logger=logger)
