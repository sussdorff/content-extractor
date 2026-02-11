"""Substack-specific extraction: archive scraping, article extraction, link classification."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..browser import ab_eval, ab_open, ab_scroll_down
from ..html_utils import html_to_markdown
from ..utils import _extract_json_array, _extract_json_object, _format_date, _url_to_slug


DEFAULT_OUTPUT = Path("output")


# ---------------------------------------------------------------------------
# Resource link detection
# ---------------------------------------------------------------------------

def classify_link(url: str, text: str) -> dict | None:
    """Classify a link by resource type."""
    if not url or url.startswith("#") or url.startswith("javascript:"):
        return None
    # Skip image URLs
    if "substackcdn.com/image" in url:
        return None

    resource_type = "external"
    if "notion.so" in url or "notion.site" in url:
        resource_type = "notion"
    elif "drive.google.com" in url or "docs.google.com" in url:
        resource_type = "google_drive"
    elif "youtu.be" in url or "youtube.com" in url:
        resource_type = "youtube"
    elif "excalidraw.com" in url:
        resource_type = "excalidraw"
    elif "substack.com" in url and "/p/" not in url:
        return None  # Skip internal substack nav links

    return {
        "url": url,
        "linkText": text.strip(),
        "context": "paragraph",
        "resourceType": resource_type,
    }


# ---------------------------------------------------------------------------
# Archive scraping
# ---------------------------------------------------------------------------

ARCHIVE_JS = """
(() => {
    const articles = [];
    const seen = new Set();

    // Strategy: find time elements and walk up to find their containing
    // archive entry, then find the article link within that container.
    const timeEls = document.querySelectorAll('time');
    for (const t of timeEls) {
        // Walk up to find a container that has an article link
        let container = t.parentElement;
        let link = null;
        for (let i = 0; i < 8 && container; i++) {
            link = container.querySelector('a[href*="/p/"]');
            if (link) break;
            container = container.parentElement;
        }
        if (!link) continue;

        const href = link.href;
        if (seen.has(href)) continue;
        seen.add(href);

        const date = t.dateTime || t.textContent.trim();

        // Find title and subtitle from article links
        const allLinks = container.querySelectorAll('a[href="' + href + '"]');
        let title = '';
        let subtitle = '';
        for (const a of allLinks) {
            const text = a.textContent.trim();
            if (!text || text.length < 3) continue;
            if (!title) { title = text; continue; }
            if (!subtitle && text !== title) { subtitle = text; }
        }

        if (title) {
            articles.push({ title, subtitle, date, url: href });
        }
    }
    return JSON.stringify(articles);
})()
"""


def scrape_archive(base_url: str, max_articles: int | None = None) -> list[dict]:
    """Scrape the Substack archive for article metadata."""
    import sys

    archive_url = base_url.rstrip("/") + "/archive"
    print(f"Opening archive: {archive_url}", file=sys.stderr)
    ab_open(archive_url)
    time.sleep(2)

    prev_count = 0
    stale_rounds = 0
    max_stale = 3

    while True:
        raw = ab_eval(ARCHIVE_JS)
        try:
            json_str = _extract_json_array(raw)
            articles = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            print(f"Warning: Could not parse archive result, retrying...", file=sys.stderr)
            articles = []

        count = len(articles)
        print(f"  Found {count} articles so far...", file=sys.stderr)

        if max_articles and count >= max_articles:
            articles = articles[:max_articles]
            break

        if count == prev_count:
            stale_rounds += 1
            if stale_rounds >= max_stale:
                break
        else:
            stale_rounds = 0

        prev_count = count
        ab_scroll_down(5)
        time.sleep(1)

    print(f"Archive scrape complete: {len(articles)} articles", file=sys.stderr)
    return articles


# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

ARTICLE_JS = """
(() => {
    // Dismiss subscribe modals/overlays
    const overlays = document.querySelectorAll(
        '[class*="modal"], [class*="overlay"], [class*="paywall"], [class*="subscribe-prompt"]'
    );
    overlays.forEach(el => {
        if (el.style) el.style.display = 'none';
    });
    const closeBtns = document.querySelectorAll(
        'button[aria-label="Close"], [class*="modal"] button, [class*="dismiss"]'
    );
    closeBtns.forEach(btn => { try { btn.click(); } catch(e) {} });

    const titleEl = document.querySelector('h1.post-title')
        || document.querySelector('.post-header h1')
        || document.querySelectorAll('h1')[1]
        || document.querySelector('h1');
    let title = titleEl ? titleEl.textContent.trim() : document.title;

    const subEl = document.querySelector(
        'h3.subtitle, .post-header h3, .subtitle'
    );
    const subtitle = subEl ? subEl.textContent.trim() : '';

    const articleEl = document.querySelector(
        '.body.markup, .available-content .body, .post-content'
    ) || document.querySelector('article .body, article');

    const contentHTML = articleEl ? articleEl.innerHTML : '';

    const authorEl = document.querySelector(
        'a.post-author, a[class*="author-name"], .post-header a[href*="/@"]'
    );
    let author = authorEl ? authorEl.textContent.trim() : '';

    let date = '';
    let ldTitle = '';
    const ldJsonEl = document.querySelector('script[type="application/ld+json"]');
    if (ldJsonEl) {
        try {
            const ld = JSON.parse(ldJsonEl.textContent);
            date = ld.datePublished || ld.dateModified || '';
            ldTitle = ld.headline || '';
            if (!author && ld.author) {
                const a = Array.isArray(ld.author) ? ld.author[0] : ld.author;
                if (a && a.name) author = a.name;
            }
        } catch(e) {}
    }
    if (!title && ldTitle) title = ldTitle;
    if (!date) {
        const timeEl = document.querySelector('time');
        date = timeEl ? (timeEl.dateTime || timeEl.textContent.trim()) : '';
    }

    const links = [];
    const seen = new Set();
    if (articleEl) {
        articleEl.querySelectorAll('a[href]').forEach(a => {
            const href = a.href;
            if (href && !seen.has(href)) {
                seen.add(href);
                links.push({ url: href, text: a.textContent.trim() });
            }
        });
    }

    let isPaywalled = false;
    const paywallEls = document.querySelectorAll(
        '[class*="paywall"], .paywall, [class*="truncated"]'
    );
    for (const el of paywallEls) {
        if (el.offsetHeight > 0 && el.offsetWidth > 0) {
            isPaywalled = true;
            break;
        }
    }

    return JSON.stringify({
        title, subtitle, author, date, contentHTML, links, isPaywalled
    });
})()
"""


def extract_article(url: str, output_dir: Path = DEFAULT_OUTPUT) -> dict:
    """Extract a single article and save to output directory."""
    import sys

    print(f"Extracting: {url}", file=sys.stderr)
    ab_open(url)
    time.sleep(2)

    raw = ab_eval(ARTICLE_JS, timeout=15)

    try:
        json_str = _extract_json_object(raw)
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing article data: {e}", file=sys.stderr)
        return {"error": str(e), "url": url}

    title = data.get("title", "Untitled")
    author = data.get("author", "")
    date_raw = data.get("date", "")
    date = _format_date(date_raw)
    content_html = data.get("contentHTML", "")
    is_paywalled = data.get("isPaywalled", False)
    raw_links = data.get("links", [])

    # Convert HTML to Markdown
    content_md = html_to_markdown(content_html) if content_html else ""
    word_count = len(content_md.split())

    # Classify resource links
    resource_links = []
    for link in raw_links:
        classified = classify_link(link.get("url", ""), link.get("text", ""))
        if classified:
            resource_links.append(classified)

    # Derive slug from URL
    slug = _url_to_slug(url)
    article_dir = output_dir / slug
    article_dir.mkdir(parents=True, exist_ok=True)

    # Determine extraction quality
    warnings = []
    if is_paywalled:
        warnings.append("Content may be truncated (paywall detected)")
    if word_count < 100:
        warnings.append(f"Low word count ({word_count})")

    quality_label = "Partial (paywall)" if is_paywalled else "Complete"

    # Write main-article.md
    article_md = f"""# {title}

**Author**: {author or 'Unknown'}
**Date**: {date}
**Source**: {url}

**Word Count**: {word_count:,} words
**Extraction Quality**: {quality_label}

---

{content_md}
"""
    (article_dir / "main-article.md").write_text(article_md, encoding="utf-8")

    # Write metadata.json
    metadata = {
        "success": not is_paywalled,
        "resourceType": "substack",
        "filepath": str(article_dir / "main-article.md"),
        "metadata": {
            "title": title,
            "author": author or "Unknown",
            "date": date,
            "url": url,
        },
        "quality": {
            "wordCount": word_count,
            "extractionMethod": "agent-browser CLI + eval",
            "warnings": warnings,
        },
        "links": resource_links,
    }
    (article_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"  Saved to {article_dir}/", file=sys.stderr)
    print(f"  Title: {title}", file=sys.stderr)
    print(f"  Words: {word_count:,}", file=sys.stderr)
    if resource_links:
        print(f"  Resource links: {len(resource_links)}", file=sys.stderr)
    if warnings:
        for w in warnings:
            print(f"  Warning: {w}", file=sys.stderr)

    # Store article_dir on metadata for dispatch_resources
    metadata["_article_dir"] = str(article_dir)
    return metadata


# ---------------------------------------------------------------------------
# Resource dispatch helpers
# ---------------------------------------------------------------------------

def dispatch_resources(
    metadata: dict, article_dir: Path, registry=None,
) -> list[dict]:
    """Extract all linked resources from an article's metadata."""
    import sys
    from dataclasses import asdict

    from ..registry import build_registry

    if registry is None:
        registry = build_registry()

    links = metadata.get("links", [])
    if not links:
        return []

    seen_urls: set[str] = set()
    results = []

    # Count extractable links for progress
    extractable = [l for l in links
                   if l.get("resourceType") not in ("external", "youtube")]
    if extractable:
        print(f"  Extracting {len(extractable)} linked resources...", file=sys.stderr)

    for link in links:
        url = link.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        resource_type = link.get("resourceType", "external")
        adapter = registry.get_adapter(url, resource_type)
        result = adapter.extract(url, link.get("linkText", ""), article_dir)
        results.append(asdict(result) if hasattr(result, '__dataclass_fields__') else result)

    return results


# ---------------------------------------------------------------------------
# Substack adapter for registry-based dispatch
# ---------------------------------------------------------------------------

class SubstackAdapter:
    """Adapter interface for Substack articles (used in registry dispatch)."""

    resource_type = "substack"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return "substack.com" in url and "/p/" in url

    def extract(self, url: str, link_text: str, article_dir: Path):
        from ..base import ExtractionResult

        metadata = extract_article(url, output_dir=article_dir.parent)
        if metadata.get("error"):
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error=metadata["error"],
            )
        return ExtractionResult(
            success=True, resource_type=self.resource_type,
            files_created=["main-article.md", "metadata.json"],
        )
