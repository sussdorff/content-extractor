"""Adapter implementations for various content sources."""

from __future__ import annotations

from .catalog import CatalogAdapter
from .drive import GoogleDriveAdapter
from .generic_web import GenericWebAdapter
from .medium import MediumAdapter
from .notion import NotionAdapter
from .substack import SubstackAdapter
from .youtube import YouTubeAdapter

__all__ = [
    "CatalogAdapter",
    "GenericWebAdapter",
    "GoogleDriveAdapter",
    "MediumAdapter",
    "NotionAdapter",
    "SubstackAdapter",
    "YouTubeAdapter",
]
