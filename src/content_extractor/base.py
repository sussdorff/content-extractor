"""Protocol, registry, and result dataclass for content extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ExtractionResult:
    """Result returned by any ContentExtractor."""

    success: bool
    resource_type: str
    files_created: list[str] = field(default_factory=list)
    error: str | None = None
    note: str | None = None


@runtime_checkable
class ContentExtractor(Protocol):
    resource_type: str

    def can_handle(self, url: str, resource_type: str) -> bool: ...
    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult: ...


class ExtractorRegistry:
    """Ordered registry of content extractors.  First match wins."""

    def __init__(self) -> None:
        self._adapters: list[ContentExtractor] = []

    def register(self, adapter: ContentExtractor) -> None:
        self._adapters.append(adapter)

    def get_adapter(self, url: str, resource_type: str) -> ContentExtractor:
        for adapter in self._adapters:
            if adapter.can_handle(url, resource_type):
                return adapter
        raise ValueError(f"No adapter for {resource_type}: {url}")
