"""Tests for the extractor registry."""

from content_extractor.base import ExtractorRegistry
from content_extractor.registry import build_registry
from content_extractor.adapters import (
    CatalogAdapter,
    GenericWebAdapter,
    GoogleDriveAdapter,
    MediumAdapter,
    NotionAdapter,
    SubstackAdapter,
    YouTubeAdapter,
)


class TestBuildRegistry:
    def test_registry_has_all_adapters(self):
        registry = build_registry()
        assert len(registry._adapters) == 7

    def test_substack_resolves(self):
        registry = build_registry()
        adapter = registry.get_adapter("https://sub.substack.com/p/test", "substack")
        assert isinstance(adapter, SubstackAdapter)

    def test_notion_resolves(self):
        registry = build_registry()
        adapter = registry.get_adapter("https://notion.so/page", "notion")
        assert isinstance(adapter, NotionAdapter)

    def test_drive_resolves(self):
        registry = build_registry()
        adapter = registry.get_adapter("https://drive.google.com/file/d/abc", "google_drive")
        assert isinstance(adapter, GoogleDriveAdapter)

    def test_youtube_resolves(self):
        registry = build_registry()
        adapter = registry.get_adapter("https://youtube.com/watch?v=x", "youtube")
        assert isinstance(adapter, YouTubeAdapter)

    def test_medium_resolves(self):
        registry = build_registry()
        adapter = registry.get_adapter("https://medium.com/@x/y", "medium")
        assert isinstance(adapter, MediumAdapter)

    def test_generic_web_fallback(self):
        registry = build_registry()
        adapter = registry.get_adapter("https://example.com/article", "web")
        assert isinstance(adapter, GenericWebAdapter)

    def test_catalog_is_last_resort(self):
        """CatalogAdapter should be last in the registry."""
        registry = build_registry()
        assert isinstance(registry._adapters[-1], CatalogAdapter)


class TestExtractorRegistry:
    def test_first_match_wins(self):
        registry = ExtractorRegistry()
        registry.register(NotionAdapter())
        registry.register(CatalogAdapter())
        adapter = registry.get_adapter("https://notion.so/page", "notion")
        assert isinstance(adapter, NotionAdapter)

    def test_raises_on_no_match(self):
        registry = ExtractorRegistry()
        # Empty registry - no adapters
        try:
            registry.get_adapter("https://example.com", "web")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
