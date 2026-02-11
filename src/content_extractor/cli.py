#!/usr/bin/env python3
"""Unified content extraction CLI with auto-detection.

Auto-detects the source type from a URL and dispatches to the correct
adapter from the content_extractor package.

Usage:
    content-extract "https://natesnewsletter.substack.com/p/..."
    content-extract "https://medium.com/@user/article"
    content-extract "https://youtube.com/watch?v=..."
    content-extract "https://notion.so/page-id"
    content-extract --from urls.txt
    content-extract --output-dir DIR "url"
    content-extract --skip-resources "url"
    content-extract --hook ./my_hook.py "url"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from .adapters.medium import MEDIUM_DOMAINS
from .adapters.substack import DEFAULT_OUTPUT, dispatch_resources, extract_article
from .base import ExtractionResult, ExtractorRegistry
from .browser import ab_close
from .hooks import (
    PostExtractionHook,
    load_hook_from_script,
    load_hooks_from_config,
    run_hooks,
)
from .registry import build_registry
from .utils import _url_to_slug


# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------

def detect_source(url: str) -> str:
    """Return a source type string based on URL patterns."""
    if "substack.com" in url:
        return "substack"
    if any(d in url for d in MEDIUM_DOMAINS):
        return "medium"
    if "youtu.be" in url or "youtube.com" in url:
        return "youtube"
    if "notion.so" in url or "notion.site" in url:
        return "notion"
    if "drive.google.com" in url or "docs.google.com" in url:
        return "google_drive"
    return "web"


def _slug_from_url(url: str) -> str:
    """Derive an output directory slug from any URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    # Substack /p/slug
    if "/p/" in path:
        return path.split("/p/")[-1]
    # YouTube watch?v=ID
    if "youtu" in url:
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [""])[0]
        if vid:
            return f"youtube-{vid}"
        # youtu.be/ID
        if parsed.netloc == "youtu.be" and path:
            return f"youtube-{path.lstrip('/')}"
    # Use last path segment, fall back to hostname
    segment = path.split("/")[-1] if path else ""
    if segment and len(segment) > 2:
        return segment
    return parsed.netloc.replace(".", "-") or "unknown"


# ---------------------------------------------------------------------------
# Single-URL extraction
# ---------------------------------------------------------------------------

def extract_url(
    url: str,
    output_dir: Path = DEFAULT_OUTPUT,
    skip_resources: bool = False,
    hooks: list[PostExtractionHook] | None = None,
) -> dict:
    """Extract content from a single URL, auto-detecting the source type.

    Args:
        url: URL to extract content from.
        output_dir: Base directory for output (default: ``output/``).
        skip_resources: If True, skip extracting linked resources.
        hooks: Optional list of post-extraction hooks to run.

    Returns:
        Dictionary with extraction results and metadata.
    """
    source = detect_source(url)
    print(f"Detected source: {source} -> {url}", file=sys.stderr)

    if source == "substack":
        out = _extract_substack(url, output_dir, skip_resources)
    else:
        out = _extract_generic(url, source, output_dir, skip_resources)

    # Run post-extraction hooks
    if hooks and out.get("success", True) and not out.get("error"):
        article_dir_str = out.get("output_dir") or out.get("_article_dir")
        if article_dir_str:
            article_dir = Path(article_dir_str)
            hook_results = run_hooks(hooks, out, article_dir)
            if hook_results:
                out["hook_results"] = [
                    {"success": r.success, "files_created": r.files_created, "error": r.error}
                    for r in hook_results
                ]

    return out


def _extract_generic(
    url: str,
    source: str,
    output_dir: Path,
    skip_resources: bool,
) -> dict:
    """Handle non-Substack URLs via the registry."""
    registry = build_registry()
    adapter = registry.get_adapter(url, source)
    print(f"Using adapter: {type(adapter).__name__}", file=sys.stderr)

    slug = _slug_from_url(url)
    article_dir = output_dir / slug
    article_dir.mkdir(parents=True, exist_ok=True)

    result = adapter.extract(url, "", article_dir)

    # Normalize result to dict
    if isinstance(result, ExtractionResult):
        out = asdict(result)
    elif isinstance(result, dict):
        out = result
    else:
        out = {"success": False, "error": "Unexpected result type"}

    out["url"] = url
    out["source_type"] = source
    out["output_dir"] = str(article_dir)

    # Resource dispatch for adapters that produce metadata with links
    if not skip_resources and out.get("success"):
        meta_file = article_dir / "metadata.json"
        if meta_file.exists():
            try:
                metadata = json.loads(meta_file.read_text(encoding="utf-8"))
                links = metadata.get("links", [])
                if links:
                    resource_registry = build_registry()
                    resource_results = dispatch_resources(
                        metadata, article_dir, registry=resource_registry,
                    )
                    out["resource_extraction"] = [
                        asdict(r) if isinstance(r, ExtractionResult) else r
                        for r in resource_results
                    ]
                    # Update metadata.json with resource results
                    metadata["resource_extraction"] = out["resource_extraction"]
                    meta_file.write_text(
                        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
            except (json.JSONDecodeError, Exception) as e:
                print(f"  Resource dispatch error: {e}", file=sys.stderr)

    print(f"  Done: {article_dir}/", file=sys.stderr)
    return out


def _extract_substack(url: str, output_dir: Path, skip_resources: bool) -> dict:
    """Handle Substack URLs via the dedicated extract_article flow."""
    metadata = extract_article(url, output_dir=output_dir)

    if metadata.get("error") or skip_resources:
        metadata.pop("_article_dir", None)
    else:
        article_dir_str = metadata.pop("_article_dir", None)
        if article_dir_str:
            article_dir = Path(article_dir_str)
            resource_registry = build_registry()
            results = dispatch_resources(
                metadata, article_dir, registry=resource_registry,
            )
            metadata["resource_extraction"] = results

            meta_file = article_dir / "metadata.json"
            if meta_file.exists():
                meta_file.write_text(
                    json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

            extracted = [r for r in results if r.get("success") and r.get("files_created")]
            if extracted:
                total_files = sum(len(r["files_created"]) for r in extracted)
                print(f"  Resources: {len(extracted)} extracted, {total_files} files created",
                      file=sys.stderr)

            metadata["output_dir"] = str(article_dir)

    metadata["source_type"] = "substack"
    return metadata


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="content-extract: Pluggable content extraction from URLs",
    )
    parser.add_argument(
        "urls", nargs="*", help="One or more URLs to extract",
    )
    parser.add_argument(
        "--from", dest="from_file", type=Path, metavar="FILE",
        help="Read URLs from a file (one per line)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--skip-resources", action="store_true",
        help="Skip extracting linked resources (Notion, Drive, etc.)",
    )
    parser.add_argument(
        "--hook", action="append", dest="hooks", metavar="SCRIPT",
        help="Path to a hook script (can be specified multiple times)",
    )
    parser.add_argument(
        "--no-config-hooks", action="store_true",
        help="Disable loading hooks from .content-extractor.toml",
    )

    args = parser.parse_args()

    # Collect URLs from arguments and/or file
    urls: list[str] = list(args.urls)
    if args.from_file:
        if not args.from_file.exists():
            print(f"Error: file not found: {args.from_file}", file=sys.stderr)
            sys.exit(1)
        for line in args.from_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        parser.print_help()
        sys.exit(1)

    # Load hooks
    all_hooks: list[PostExtractionHook] = []
    if args.hooks:
        for hook_path in args.hooks:
            try:
                all_hooks.append(load_hook_from_script(hook_path))
            except (FileNotFoundError, ValueError, TypeError) as e:
                print(f"Error loading hook {hook_path}: {e}", file=sys.stderr)
                sys.exit(1)
    if not args.no_config_hooks:
        all_hooks.extend(load_hooks_from_config())

    try:
        if len(urls) == 1:
            result = extract_url(
                urls[0],
                output_dir=args.output_dir,
                skip_resources=args.skip_resources,
                hooks=all_hooks or None,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            results = []
            for i, url in enumerate(urls, 1):
                print(f"\n[{i}/{len(urls)}] {url}", file=sys.stderr)
                result = extract_url(
                    url,
                    output_dir=args.output_dir,
                    skip_resources=args.skip_resources,
                    hooks=all_hooks or None,
                )
                results.append(result)
                if i < len(urls):
                    time.sleep(1)
            print(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        ab_close()


if __name__ == "__main__":
    main()
