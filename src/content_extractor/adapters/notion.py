"""Notion page content extraction adapter.

Extracts page content only. Prompt splitting is a consumer-side concern
handled via the post-extraction hook system.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ..browser import ab_eval, ab_open, ab_scroll_down


class NotionAdapter:
    """Extract Notion page content."""

    resource_type = "notion"

    def can_handle(self, url: str, resource_type: str) -> bool:
        return "notion.so" in url or "notion.site" in url

    def extract(self, url: str, link_text: str, article_dir: Path) -> dict:
        print(f"  [Notion] Extracting: {url}", file=sys.stderr)
        try:
            ab_open(url)
            time.sleep(3)  # Notion is slow to render

            # Scroll to load lazy content
            for _ in range(3):
                ab_scroll_down(3)
                time.sleep(1)

            # Extract page text
            text = ab_eval("""
                (() => {
                    const main = document.querySelector('main')
                        || document.querySelector('[class*="notion-page-content"]')
                        || document.querySelector('.notion-page-content')
                        || document.querySelector('[class*="layout-content"]')
                        || document.body;
                    return main ? main.innerText : '';
                })()
            """, timeout=15)

            if not text or len(text.strip()) < 50:
                return {"success": False, "resource_type": "notion",
                        "files_created": [], "error": "Empty page or failed to load"}

            # Login wall check
            text_lower = text.lower()
            if any(phrase in text_lower for phrase in
                   ["log in", "sign up", "continue with google", "continue with apple"]):
                if len(text.strip()) < 200:
                    return {"success": False, "resource_type": "notion",
                            "files_created": [], "error": "Login required"}

            # Get page title
            title = ab_eval("""
                (() => {
                    const h1 = document.querySelector('h1');
                    return h1 ? h1.innerText.trim() : document.title;
                })()
            """, timeout=10) or "Notion Page"

            # Determine filename: notion-content.md or notion-{slug}.md for multiple
            notion_files = list(article_dir.glob("notion-*.md"))
            if notion_files:
                # Multiple notion links - use slug from URL
                slug = url.rstrip("/").split("/")[-1].split("-")[-1][:12]
                filename = f"notion-{slug}.md"
            else:
                filename = "notion-content.md"

            # Write markdown with metadata header
            md_content = f"# {title}\n\n"
            md_content += f"> Source: {url}\n"
            md_content += f"> Extracted via: agent-browser (NotionAdapter)\n\n"
            md_content += "---\n\n"
            md_content += text.strip() + "\n"

            (article_dir / filename).write_text(md_content, encoding="utf-8")
            files_created = [filename]
            print(f"  [Notion] Saved {filename} ({len(text):,} chars)", file=sys.stderr)

            return {"success": True, "resource_type": "notion",
                    "files_created": files_created}

        except Exception as e:
            print(f"  [Notion] Error: {e}", file=sys.stderr)
            return {"success": False, "resource_type": "notion",
                    "files_created": [], "error": str(e)}
