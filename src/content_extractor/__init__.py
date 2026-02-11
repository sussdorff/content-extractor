"""content-extractor — pluggable content extraction framework."""

from __future__ import annotations

from .base import ContentExtractor, ExtractionResult, ExtractorRegistry
from .hooks import HookResult, PostExtractionHook

__all__ = [
    "ContentExtractor",
    "ExtractionResult",
    "ExtractorRegistry",
    "HookResult",
    "PostExtractionHook",
]
