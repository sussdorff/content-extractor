"""Minimal HTML to Markdown converter (stdlib only)."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _HTMLToMD(HTMLParser):
    """Lightweight HTML to Markdown converter."""

    BLOCK_TAGS = {"p", "div", "section", "article", "blockquote", "li", "tr"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._tag_stack: list[str] = []
        self._href: str | None = None
        self._link_text_parts: list[str] = []
        self._in_link = False
        self._list_depth = 0
        self._ordered = False
        self._li_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        self._tag_stack.append(tag)

        if tag in self.HEADING_TAGS:
            level = int(tag[1])
            self._parts.append("\n\n" + "#" * level + " ")
        elif tag == "p":
            self._parts.append("\n\n")
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "a":
            self._in_link = True
            self._href = attrs_dict.get("href")
            self._link_text_parts = []
        elif tag == "strong" or tag == "b":
            self._parts.append("**")
        elif tag == "em" or tag == "i":
            self._parts.append("*")
        elif tag == "code":
            self._parts.append("`")
        elif tag == "pre":
            self._parts.append("\n\n```\n")
        elif tag == "blockquote":
            self._parts.append("\n\n> ")
        elif tag == "ul":
            self._list_depth += 1
            self._ordered = False
            self._li_count = 0
        elif tag == "ol":
            self._list_depth += 1
            self._ordered = True
            self._li_count = 0
        elif tag == "li":
            self._li_count += 1
            indent = "  " * (self._list_depth - 1)
            if self._ordered:
                self._parts.append(f"\n{indent}{self._li_count}. ")
            else:
                self._parts.append(f"\n{indent}- ")
        elif tag == "hr":
            self._parts.append("\n\n---\n\n")
        elif tag == "img":
            alt = attrs_dict.get("alt", "")
            src = attrs_dict.get("src", "")
            if src:
                self._parts.append(f"\n\n![{alt}]({src})\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag in self.HEADING_TAGS:
            self._parts.append("\n")
        elif tag == "a":
            text = "".join(self._link_text_parts).strip()
            if self._href and text:
                self._parts.append(f"[{text}]({self._href})")
            elif text:
                self._parts.append(text)
            self._in_link = False
            self._href = None
        elif tag == "strong" or tag == "b":
            self._parts.append("**")
        elif tag == "em" or tag == "i":
            self._parts.append("*")
        elif tag == "code":
            self._parts.append("`")
        elif tag == "pre":
            self._parts.append("\n```\n\n")
        elif tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)
            self._parts.append("\n")
        elif tag == "p":
            pass  # handled by next starttag

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text_parts.append(data)
        else:
            self._parts.append(data)

    def get_markdown(self) -> str:
        text = "".join(self._parts)
        # Clean up excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Fix list items with blank lines between bullet and content
        text = re.sub(r"(\n\s*[-\d]+[.)]\s*)\n+\n", r"\1", text)
        return text.strip()


def html_to_markdown(html: str) -> str:
    """Convert HTML string to Markdown."""
    parser = _HTMLToMD()
    parser.feed(html)
    return parser.get_markdown()
