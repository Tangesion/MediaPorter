import unittest

from music_picker_app.url_parser import extract_urls, filter_supported_urls


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
            "https://www.bilibili.com/video/BV123",
            "https://youtube.com/watch?v=1",
        ]
        self.assertEqual(
            filter_supported_urls(urls),
            ["https://www.bilibili.com/video/BV123", "https://b23.tv/abcd"],
        )


if __name__ == "__main__":
    unittest.main()
