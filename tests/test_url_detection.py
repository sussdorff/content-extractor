"""Tests for URL detection and slug derivation."""

from content_extractor.cli import detect_source, _slug_from_url


class TestDetectSource:
    def test_substack(self):
        assert detect_source("https://natesnewsletter.substack.com/p/some-article") == "substack"

    def test_medium(self):
        assert detect_source("https://medium.com/@user/some-article-abc123") == "medium"

    def test_medium_custom_domain(self):
        assert detect_source("https://towardsdatascience.com/article") == "medium"

    def test_youtube_watch(self):
        assert detect_source("https://youtube.com/watch?v=abc123") == "youtube"

    def test_youtube_short(self):
        assert detect_source("https://youtu.be/abc123") == "youtube"

    def test_notion(self):
        assert detect_source("https://notion.so/page-id") == "notion"

    def test_notion_site(self):
        assert detect_source("https://example.notion.site/page") == "notion"

    def test_google_drive(self):
        assert detect_source("https://drive.google.com/file/d/abc/view") == "google_drive"

    def test_google_docs(self):
        assert detect_source("https://docs.google.com/document/d/abc/edit") == "google_drive"

    def test_generic_web(self):
        assert detect_source("https://example.com/article") == "web"


    def test_youtube_channel_handle(self):
        assert detect_source("https://www.youtube.com/@indydevdan/videos") == "youtube"

    def test_youtube_channel_id(self):
        assert detect_source("https://www.youtube.com/channel/UCxyz123") == "youtube"

    def test_youtube_playlist(self):
        assert detect_source("https://www.youtube.com/playlist?list=PLxyz123") == "youtube"


class TestSlugFromUrl:
    def test_substack_slug(self):
        assert _slug_from_url("https://sub.substack.com/p/my-article") == "my-article"

    def test_youtube_watch(self):
        assert _slug_from_url("https://youtube.com/watch?v=abc123") == "youtube-abc123"

    def test_youtube_short(self):
        assert _slug_from_url("https://youtu.be/abc123") == "youtube-abc123"

    def test_youtube_channel_handle(self):
        assert _slug_from_url("https://www.youtube.com/@indydevdan") == "youtube-indydevdan"

    def test_youtube_channel_handle_with_videos(self):
        assert _slug_from_url("https://www.youtube.com/@indydevdan/videos") == "youtube-indydevdan"

    def test_youtube_channel_id(self):
        assert _slug_from_url("https://www.youtube.com/channel/UCxyz123") == "youtube-UCxyz123"

    def test_youtube_playlist_slug(self):
        assert _slug_from_url("https://www.youtube.com/playlist?list=PLxyz123") == "youtube-PLxyz123"

    def test_path_segment(self):
        assert _slug_from_url("https://example.com/blog/my-post") == "my-post"

    def test_hostname_fallback(self):
        assert _slug_from_url("https://example.com/") == "example-com"
