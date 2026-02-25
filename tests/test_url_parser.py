import unittest

from music_picker_app.url_parser import (
    diagnose_urls,
    extract_urls,
    filter_supported_urls,
    is_supported_url,
    parse_download_entries,
)


class UrlParserTests(unittest.TestCase):
    def test_extract_urls_from_mixed_text(self) -> None:
        text = "hello https://www.bilibili.com/video/BV1xx foo, https://example.com/a"
        self.assertEqual(
            extract_urls(text),
            ["https://www.bilibili.com/video/BV1xx", "https://example.com/a"],
        )

    def test_filter_supported_urls_and_deduplicate(self) -> None:
        urls = [
            "https://www.bilibili.com/video/BV123",
            "https://b23.tv/abcd",
            "https://www.bilibili.com/bangumi/play/ep123456",
            "https://www.bilibili.com/video/BV123",
            "https://youtube.com/watch?v=1",
        ]
        self.assertEqual(
            filter_supported_urls(urls),
            [
                "https://www.bilibili.com/video/BV123",
                "https://b23.tv/abcd",
                "https://www.bilibili.com/bangumi/play/ep123456",
            ],
        )

    def test_is_supported_url_for_movie_and_bangumi(self) -> None:
        self.assertTrue(is_supported_url("https://www.bilibili.com/bangumi/play/ss123"))
        self.assertTrue(is_supported_url("https://www.bilibili.com/movie/123"))
        self.assertFalse(is_supported_url("https://example.com/bangumi/play/ep1"))

    def test_filter_supported_url_with_trailing_punctuation(self) -> None:
        urls = ['"https://www.bilibili.com/video/BV18ofkBnE62/?a=1&b=2".']
        self.assertEqual(
            filter_supported_urls(urls),
            ["https://www.bilibili.com/video/BV18ofkBnE62/?a=1&b=2"],
        )

    def test_diagnose_urls_gives_reason(self) -> None:
        valid, diagnostics = diagnose_urls("https://example.com/v/1")
        self.assertEqual(valid, [])
        self.assertTrue(any("host is not bilibili/b23" in item for item in diagnostics))

    def test_extract_urls_with_fullwidth_symbols(self) -> None:
        text = (
            "https\uff1a\uff0f\uff0fwww\uff0ebilibili\uff0ecom"
            "\uff0fvideo\uff0fBV18ofkBnE62\uff1fa=1\uff06b=2"
        )
        self.assertEqual(
            extract_urls(text),
            ["https://www.bilibili.com/video/BV18ofkBnE62?a=1&b=2"],
        )

    def test_parse_download_entries_with_custom_filename(self) -> None:
        text = (
            "https://www.bilibili.com/video/BV1xx || song_a\n"
            "https://www.bilibili.com/bangumi/play/ep1\n"
        )
        tasks, diagnostics = parse_download_entries(text)
        self.assertEqual(diagnostics, [])
        self.assertEqual(tasks[0].url, "https://www.bilibili.com/video/BV1xx")
        self.assertEqual(tasks[0].filename, "song_a")
        self.assertEqual(tasks[1].filename, None)


if __name__ == "__main__":
    unittest.main()
