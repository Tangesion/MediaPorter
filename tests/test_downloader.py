import tempfile
import unittest
from pathlib import Path

from mediaporter_app.downloader import MediaDownloader


class DownloaderTests(unittest.TestCase):
    def test_select_format_by_video_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="1080")
            downloader.ffmpeg_available = True
            self.assertEqual(
                downloader._select_format(),
                "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            )

            downloader.video_quality = "720"
            self.assertEqual(
                downloader._select_format(),
                "bestvideo[height<=720]+bestaudio/best[height<=720]",
            )

            downloader.video_quality = "auto"
            self.assertEqual(downloader._select_format(), "bestvideo+bestaudio/best")

    def test_select_format_video_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="1080")
            downloader.ffmpeg_available = False
            self.assertEqual(
                downloader._select_format(),
                "best[height<=1080][vcodec!=none][acodec!=none]",
            )

            downloader.video_quality = "auto"
            self.assertEqual(downloader._select_format(), "best[vcodec!=none][acodec!=none]")

    def test_error_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="auto")
            downloader.ffmpeg_available = True
            self.assertIn("DRM-protected", downloader._map_download_error("DRM restricted"))
            self.assertIn("Login/VIP", downloader._map_download_error("HTTP Error 403"))
            self.assertIn("updating yt-dlp", downloader._map_download_error("Unable to extract"))
            self.assertIn("WinError 10013", downloader._map_download_error("TransportError: WinError 10013"))
            self.assertIn(
                "Requested quality/format is unavailable",
                downloader._map_download_error(
                    "\x1b[0;31mERROR:\x1b[0m Requested format is not available"
                ),
            )

    def test_pick_video_format_selector_with_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="720")
            downloader.ffmpeg_available = True
            formats = [
                {"format_id": "v1080", "vcodec": "avc1", "acodec": "none", "height": 1080, "tbr": 3500},
                {"format_id": "v720", "vcodec": "avc1", "acodec": "none", "height": 720, "tbr": 2200},
                {"format_id": "a128", "vcodec": "none", "acodec": "aac", "abr": 128},
            ]
            self.assertEqual(downloader._pick_video_format_selector(formats), "v720+a128")

    def test_pick_video_format_selector_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="1080")
            downloader.ffmpeg_available = False
            formats = [
                {"format_id": "p480", "vcodec": "avc1", "acodec": "aac", "height": 480, "tbr": 800},
                {"format_id": "p720", "vcodec": "avc1", "acodec": "aac", "height": 720, "tbr": 1400},
            ]
            self.assertEqual(downloader._pick_video_format_selector(formats), "p720")

    def test_pick_video_only_when_no_progressive_and_no_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="auto")
            downloader.ffmpeg_available = False
            formats = [
                {"format_id": "v1080", "vcodec": "avc1", "acodec": "none", "height": 1080, "tbr": 3200},
                {"format_id": "a128", "vcodec": "none", "acodec": "aac", "abr": 128},
            ]
            self.assertIsNone(downloader._pick_video_format_selector(formats))

    def test_summarize_formats(self) -> None:
        formats = [
            {"format_id": "p720", "ext": "mp4", "height": 720, "fps": 30, "tbr": 1400, "vcodec": "avc1", "acodec": "aac"},
            {"format_id": "a128", "ext": "m4a", "tbr": 128, "vcodec": "none", "acodec": "aac"},
        ]
        summary = MediaDownloader._summarize_formats(formats, limit=5)
        self.assertIn("id=p720", summary)
        self.assertIn("id=a128", summary)

    def test_build_probe_options_does_not_force_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="1080")
            probe_opts = downloader._build_probe_options()
            self.assertNotIn("format", probe_opts)
            self.assertEqual(probe_opts.get("skip_download"), True)

    def test_error_mapping_no_ffmpeg_video_requires_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader(Path(temp_dir), mode="video", video_quality="auto")
            downloader.ffmpeg_available = False
            message = downloader._map_download_error("Requested format is not available")
            self.assertIn("Install ffmpeg", message)

    def test_format_login_report(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "isLogin": True,
                "uname": "tester",
                "mid": 123,
                "vipType": 2,
                "vipStatus": 1,
            },
        }
        report = MediaDownloader._format_login_report(payload, "browser")
        self.assertIn("isLogin: True", report)
        self.assertIn("active VIP", report)

    def test_sanitize_filename(self) -> None:
        self.assertEqual(MediaDownloader._sanitize_filename("a:b*?<>|"), "a_b_")


if __name__ == "__main__":
    unittest.main()
