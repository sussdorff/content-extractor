"""Medium article extraction adapter."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from ..base import ExtractionResult
from ..browser import ab_open, ab_eval, ab_scroll_down
from ..html_utils import html_to_markdown
from ..utils import _format_date

MEDIUM_DOMAINS = ("medium.com", "towardsdatascience.com", "betterprogramming.pub")

DISMISS_PAYWALL_JS = """
(() => {
    document.querySelectorAll(
        '[data-testid="paywall"], [class*="meteredContent"], [class*="overlay"], [class*="paywall"]'
    ).forEach(el => { if (el.style) el.style.display = 'none'; });
    document.body.style.overflow = 'auto';
    document.querySelectorAll(
        'button[aria-label="close"], button[aria-label="Close"], [class*="dismiss"] button'
    ).forEach(btn => { try { btn.click(); } catch(e) {} });
})()
"""

EXTRACT_JS = """
(() => {
    const articleEl = document.querySelector('article')
        || document.querySelector('section[data-testid="post-content"]')
        || document.querySelector('[role="main"] section');
    const contentHTML = articleEl ? articleEl.innerHTML : '';

    const h1 = document.querySelector('article h1') || document.querySelector('h1');
    let title = h1 ? h1.textContent.trim() : document.title;

    const authorEl = document.querySelector('a[data-testid="authorName"]')
        || document.querySelector('[rel="author"]')
        || document.querySelector('a[href*="/@"]');
    let author = authorEl ? authorEl.textContent.trim() : '';

    let date = '';
    const ldEls = document.querySelectorAll('script[type="application/ld+json"]');
    for (const ldEl of ldEls) {
        try {
            const ld = JSON.parse(ldEl.textContent);
            if (ld.datePublished) date = ld.datePublished;
            if (ld.headline && !title) title = ld.headline;
            if (!author && ld.author) {
                const a = Array.isArray(ld.author) ? ld.author[0] : ld.author;
                if (a && a.name) author = a.name;
            }
            if (date) break;
        } catch(e) {}
    }
    if (!date) {
        const timeEl = document.querySelector('time');
        date = timeEl ? (timeEl.dateTime || timeEl.textContent.trim()) : '';
    }

    const paywallEl = document.querySelector('[data-testid="paywall"]');
    const memberOnly = document.body.innerText.includes('Member-only story');
    const isPaywalled = !!(paywallEl && paywallEl.offsetHeight > 0) || memberOnly;

    const links = [];
    const seen = new Set();
    if (articleEl) {
        articleEl.querySelectorAll('a[href]').forEach(a => {
            const href = a.href;
            if (href && !seen.has(href) && !href.startsWith('#') && !href.startsWith('javascript:')) {
                seen.add(href);
                links.push({ url: href, text: a.textContent.trim() });
            }
        });
    }

    return JSON.stringify({ title, author, date, contentHTML, links, isPaywalled });
})()
"""


class MediumAdapter:
    resource_type = "medium"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return any(d in url for d in MEDIUM_DOMAINS)

    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult:
        print(f"  [Medium] Extracting: {url}", file=sys.stderr)
        try:
            ab_open(url)
            time.sleep(3)

            ab_eval(DISMISS_PAYWALL_JS, timeout=10)
            time.sleep(1)

            for _ in range(2):
                ab_scroll_down(3)
                time.sleep(1)

            raw = ab_eval(EXTRACT_JS, timeout=15)

            idx = raw.find("{")
            if idx == -1:
                return ExtractionResult(
                    success=False, resource_type="medium",
                    error="Failed to extract article data",
                )
            depth, end = 0, idx
            for i in range(idx, len(raw)):
                if raw[i] == "{":
                    depth += 1
                elif raw[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            data = json.loads(raw[idx:end])

            title = data.get("title", "") or link_text or "Untitled"
            author = data.get("author", "")
            date_raw = data.get("date", "")
            date = _format_date(date_raw)
            content_html = data.get("contentHTML", "")
            is_paywalled = data.get("isPaywalled", False)
            raw_links = data.get("links", [])

            content_md = html_to_markdown(content_html) if content_html else ""
            word_count = len(content_md.split())

            if word_count < 20 and not content_md.strip():
                return ExtractionResult(
                    success=False, resource_type="medium",
                    error="Empty or near-empty content extracted",
                )

            article_dir.mkdir(parents=True, exist_ok=True)

            warnings = []
            if is_paywalled:
                warnings.append("Content may be truncated (paywall/member-only)")
            if word_count < 100:
                warnings.append(f"Low word count ({word_count})")
            quality_label = "Partial (paywall)" if is_paywalled else "Complete"

            article_md = f"# {title}\n\n"
            if author:
                article_md += f"**Author**: {author}\n"
            if date:
                article_md += f"**Date**: {date}\n"
            article_md += f"**Source**: {url}\n\n"
            article_md += f"**Word Count**: {word_count:,} words\n"
            article_md += f"**Extraction Quality**: {quality_label}\n\n"
            article_md += "---\n\n"
            article_md += content_md + "\n"

            (article_dir / "main-article.md").write_text(article_md, encoding="utf-8")

            resource_links = []
            for link in raw_links:
                href = link.get("url", "")
                if not href:
                    continue
                rtype = "external"
                if "notion.so" in href or "notion.site" in href:
                    rtype = "notion"
                elif "drive.google.com" in href or "docs.google.com" in href:
                    rtype = "google_drive"
                elif "youtu.be" in href or "youtube.com" in href:
                    rtype = "youtube"
                resource_links.append({
                    "url": href,
                    "linkText": link.get("text", "").strip(),
                    "context": "paragraph",
                    "resourceType": rtype,
                })

            metadata = {
                "success": not is_paywalled,
                "resourceType": "medium",
                "filepath": str(article_dir / "main-article.md"),
                "metadata": {
                    "title": title,
                    "author": author,
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
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            files_created = ["main-article.md", "metadata.json"]
            print(f"  [Medium] Saved {word_count:,} words, {len(resource_links)} links", file=sys.stderr)

            return ExtractionResult(
                success=True,
                resource_type="medium",
                files_created=files_created,
                note=f"{word_count} words" + (", paywalled" if is_paywalled else ""),
            )

        except Exception as e:
            print(f"  [Medium] Error: {e}", file=sys.stderr)
            return ExtractionResult(
                success=False, resource_type="medium", error=str(e),
            )
