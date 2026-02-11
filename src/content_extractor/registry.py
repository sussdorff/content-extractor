"""Default extractor registry builder."""

from __future__ import annotations

from .base import ExtractorRegistry
from .adapters.catalog import CatalogAdapter
from .adapters.drive import GoogleDriveAdapter
from .adapters.generic_web import GenericWebAdapter
from .adapters.medium import MediumAdapter
from .adapters.notion import NotionAdapter
from .adapters.substack import SubstackAdapter
from .adapters.youtube import YouTubeAdapter


def build_registry() -> ExtractorRegistry:
    """Build registry with all available adapters (order matters: first match wins)."""
    registry = ExtractorRegistry()
    registry.register(SubstackAdapter())
    registry.register(NotionAdapter())
    registry.register(GoogleDriveAdapter())
    registry.register(YouTubeAdapter())
    registry.register(MediumAdapter())
    registry.register(GenericWebAdapter())   # general web fallback
    registry.register(CatalogAdapter())      # metadata-only fallback (lowest priority)
    return registry
