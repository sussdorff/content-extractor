"""Fallback adapter that catalogs resources without extraction."""

from __future__ import annotations

from pathlib import Path


class CatalogAdapter:
    """Fallback: catalog the resource in metadata without extraction."""

    resource_type = "catalog"

    def can_handle(self, url: str, resource_type: str) -> bool:
        return True  # Always matches as fallback

    def extract(self, url: str, link_text: str, article_dir: Path) -> dict:
        # Infer type from URL for metadata
        if "youtu" in url:
            rtype = "youtube"
        elif "notion" in url:
            rtype = "notion"
        elif "drive.google" in url or "docs.google" in url:
            rtype = "google_drive"
        else:
            rtype = "external"
        return {"success": True, "resource_type": rtype,
                "files_created": [], "note": "Catalogued only"}
