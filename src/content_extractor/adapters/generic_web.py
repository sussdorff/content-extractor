"""Generic web page extraction using readability-style heuristics."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..base import ExtractionResult
from ..browser import ab_open, ab_eval
from ..html_utils import html_to_markdown
from ..utils import _format_date

_CONTENT_JS = """(() => {
    const selectors = ['article', '[role="main"]', 'main', '.post-content', '.entry-content', '.content'];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText.length > 200) {
            return JSON.stringify({html: el.innerHTML, text: el.innerText.length});
        }
    }
    return JSON.stringify({html: document.body.innerHTML, text: document.body.innerText.length});
})()"""

_META_JS = """(() => {
    const m = {};
    const h1 = document.querySelector('h1');
    m.title = h1 ? h1.innerText.trim() : document.title;
    const ld = document.querySelector('script[type="application/ld+json"]');
    if (ld) {
        try {
            const d = JSON.parse(ld.textContent);
            const obj = Array.isArray(d) ? d[0] : d;
            m.author = m.author || obj.author?.name || obj.author?.[0]?.name || '';
            m.date = m.date || obj.datePublished || '';
        } catch(e) {}
    }
    const og = (n) => {
        const el = document.querySelector(`meta[property="${n}"]`) || document.querySelector(`meta[name="${n}"]`);
        return el ? el.content : '';
    };
    m.title = m.title || og('og:title');
    m.author = m.author || og('article:author') || og('author');
    m.date = m.date || og('article:published_time') || og('date');
    return JSON.stringify(m);
})()"""


class GenericWebAdapter:
    resource_type = "web"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return True  # Fallback - always matches (lowest priority in registry)

    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult:
        ab_open(url)
        time.sleep(2)

        raw_content = ab_eval(_CONTENT_JS)
        try:
            content_data = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError):
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error=f"Failed to extract content from {url}",
            )

        html = content_data.get("html", "")
        if not html:
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error="No content found on page",
            )

        markdown = html_to_markdown(html)

        raw_meta = ab_eval(_META_JS)
        try:
            meta = json.loads(raw_meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}

        title = meta.get("title") or link_text or "Untitled"
        author = meta.get("author", "")
        date_raw = meta.get("date", "")
        date_fmt = _format_date(date_raw) if date_raw else ""

        lines = [f"# {title}\n"]
        if author:
            lines.append(f"**Author:** {author}  ")
        if date_fmt:
            lines.append(f"**Date:** {date_fmt}  ")
        lines.append(f"**URL:** {url}\n")
        lines.append(markdown + "\n")

        files_created: list[str] = []

        article_dir.mkdir(parents=True, exist_ok=True)

        md_path = article_dir / "main-article.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")
        files_created.append(str(md_path))

        metadata = {
            "title": title,
            "author": author,
            "date": date_raw,
            "url": url,
            "resourceType": self.resource_type,
        }
        meta_path = article_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        files_created.append(str(meta_path))

        return ExtractionResult(
            success=True, resource_type=self.resource_type,
            files_created=files_created,
        )
