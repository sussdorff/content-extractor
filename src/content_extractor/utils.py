"""Shared utility functions for extraction."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def _extract_json_array(raw: str) -> str:
    """Extract a JSON array from agent-browser eval output."""
    # agent-browser --json wraps result; find the array
    idx = raw.find("[")
    if idx == -1:
        raise ValueError(f"No JSON array found in: {raw[:200]}")
    # Find matching bracket
    depth = 0
    for i in range(idx, len(raw)):
        if raw[i] == "[":
            depth += 1
        elif raw[i] == "]":
            depth -= 1
            if depth == 0:
                return raw[idx : i + 1]
    raise ValueError("Unbalanced JSON array")


def _extract_json_object(raw: str) -> str:
    """Extract a JSON object from agent-browser eval output."""
    idx = raw.find("{")
    if idx == -1:
        raise ValueError(f"No JSON object found in: {raw[:200]}")
    depth = 0
    for i in range(idx, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return raw[idx : i + 1]
    raise ValueError("Unbalanced JSON object")


def _format_date(date_str: str) -> str:
    """Format an ISO date string to 'Mon DD, YYYY' format."""
    if not date_str:
        return ""
    from datetime import datetime

    # Try ISO format: 2025-11-18T16:56:38+01:00
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    # Already formatted?
    if re.match(r"[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}", date_str):
        return date_str
    return date_str


def _url_to_slug(url: str) -> str:
    """Extract slug from a Substack URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    # /p/some-article-slug -> some-article-slug
    if "/p/" in path:
        return path.split("/p/")[-1]
    return path.split("/")[-1] or "unknown"
