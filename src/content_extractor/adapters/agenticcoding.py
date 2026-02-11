"""AgenticCoding.school extraction: class content, transcripts, and Excalidraw diagrams."""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..base import ExtractionResult
from ..utils import _extract_json_array, _extract_json_object

PROFILE = str(Path.home() / ".agent-browser-profiles" / "agenticcoding")
SESSION = "agenticcoding"


# ---------------------------------------------------------------------------
# Browser helpers (dedicated session/profile for agenticcoding.school)
# ---------------------------------------------------------------------------

def _ab(*args: str, timeout: int = 30) -> str:
    """Run an agent-browser command with agenticcoding profile."""
    import subprocess

    cmd = ["agent-browser", "--session", SESSION, "--profile", PROFILE]
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def _ab_eval(js: str, timeout: int = 30) -> str:
    """Execute JavaScript and return the result string."""
    import subprocess

    cmd = [
        "agent-browser", "--session", SESSION, "--profile", PROFILE,
        "--json", "eval", "--stdin",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, input=js,
    )
    raw = result.stdout.strip()
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict) and "data" in wrapper:
            return wrapper["data"].get("result", "")
    except (json.JSONDecodeError, TypeError):
        pass
    return raw


def _ab_open(url: str) -> None:
    """Navigate to a URL."""
    _ab("open", url)
    time.sleep(3)


def _ab_close() -> None:
    """Close the browser session."""
    try:
        _ab("close")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# JavaScript snippets
# ---------------------------------------------------------------------------

LIST_CLASSES_JS = """
(() => {
    const classes = [];
    const seen = new Set();
    document.querySelectorAll('a[href*="/member/class/"]').forEach(a => {
        const href = a.href;
        if (seen.has(href)) return;
        seen.add(href);
        const text = a.textContent.trim();
        if (text.length > 2 && !text.includes('\\n')) {
            classes.push({ title: text, url: href });
        }
    });
    return JSON.stringify(classes);
})()
"""

CLASS_STRUCTURE_JS = """
(() => {
    const result = {
        title: document.title.replace(/ - Agentic Coding School$/, ''),
        url: window.location.href,
        chapters: []
    };

    const mainGrid = document.querySelector('.grid.grid-cols-1.gap-6');
    if (!mainGrid) return JSON.stringify(result);

    const rightCol = mainGrid.children[1];
    if (!rightCol) return JSON.stringify(result);

    let currentChapter = null;
    const elements = rightCol.querySelectorAll('h3, li.flex.items-center');
    elements.forEach(el => {
        if (el.tagName === 'H3') {
            currentChapter = { name: el.textContent.trim(), lessons: [] };
            result.chapters.push(currentChapter);
        } else if (el.tagName === 'LI' && currentChapter) {
            const flex1 = el.querySelector('span.flex-1');
            const nameNode = flex1?.childNodes[0];
            const durSpan = el.querySelector('span.ml-2');
            const isActive = el.className.includes('font-medium');

            // Try to extract the URL with videoId by triggering the click handler
            // Lessons are clickable <li> elements; we can read data attributes or
            // the URL after click. For now, capture what's available statically.
            currentChapter.lessons.push({
                title: nameNode?.textContent?.trim() || '',
                duration: durSpan?.textContent?.trim() || '',
                isActive
            });
        }
    });

    return JSON.stringify(result);
})()
"""

CLICK_LESSON_JS = """
(() => {{
    const lis = document.querySelectorAll('li.flex.items-center.gap-2.text-sm.cursor-pointer');
    const target = lis[{idx}];
    if (!target) return JSON.stringify({{error: 'Lesson index {idx} not found'}});
    target.click();
    return JSON.stringify({{clicked: target.textContent.trim().substring(0, 80)}});
}})()
"""

CLICK_TAB_JS = """
(() => {{
    const tabs = document.querySelectorAll('[role="tab"]');
    let target = null;
    for (const t of tabs) {{
        if (t.textContent.trim() === '{tab_name}') {{
            target = t;
            break;
        }}
    }}
    if (!target) return JSON.stringify({{error: '{tab_name} tab not found'}});

    const rect = target.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(type => {{
        target.dispatchEvent(new MouseEvent(type, {{
            bubbles: true, cancelable: true, clientX: x, clientY: y, view: window
        }}));
    }});

    return JSON.stringify({{clicked: '{tab_name}'}});
}})()
"""

GET_TRANSCRIPT_JS = """
(() => {
    const panel = document.querySelector('[role="tabpanel"][data-state="active"]');
    if (!panel) return JSON.stringify({error: 'No active panel'});

    // The transcript text has timestamps like "0:00text0:02more text"
    // Get all text content, preserving line structure
    const text = panel.textContent.trim();

    // Also get the HTML for potential structured parsing
    const html = panel.innerHTML;

    return JSON.stringify({ text, html });
})()
"""

GET_DESCRIPTION_JS = """
(() => {
    const panel = document.querySelector('[role="tabpanel"][data-state="active"]');
    if (!panel) return JSON.stringify({error: 'No active panel', links: []});

    const links = [];
    panel.querySelectorAll('a[href]').forEach(a => {
        links.push({ text: a.textContent.trim(), href: a.href });
    });

    return JSON.stringify({
        text: panel.textContent.trim(),
        html: panel.innerHTML,
        links
    });
})()
"""

GET_LESSON_META_JS = """
(() => {
    const result = { url: window.location.href };

    // Published date
    const dateMatch = document.body.innerText.match(/Published\\s+([\\w]+\\s+\\d{1,2},?\\s+\\d{4})/);
    result.publishedDate = dateMatch ? dateMatch[1].trim() : null;

    // Video embed URL (Bunny.net CDN)
    const iframe = document.querySelector('.rounded-lg.border.bg-card iframe[src*="mediadelivery.net"]');
    result.videoUrl = iframe ? iframe.src.split('?')[0] : null;

    return JSON.stringify(result);
})()
"""


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def _parse_transcript(raw_text: str) -> str:
    """Parse timestamped transcript into readable markdown.

    Input format: "0:00First sentence0:02continues here..."
    Output: timestamped lines.
    """
    # Strip language tabs prefix (e.g. "EnglishEspañolArabicCopy transcript")
    text = re.sub(r'^.*?Copy transcript', '', raw_text, count=1)
    if not text:
        text = raw_text

    # Split on timestamp patterns like "0:00", "1:23", "12:34"
    parts = re.split(r'(\d{1,2}:\d{2})', text)

    lines = []
    i = 0
    while i < len(parts):
        part = parts[i].strip()
        if re.match(r'^\d{1,2}:\d{2}$', part) and i + 1 < len(parts):
            content = parts[i + 1].strip()
            if content:
                lines.append(f"[{part}] {content}")
            i += 2
        else:
            i += 1

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_published_date(date_str: str | None) -> str | None:
    """Parse a published date like 'Feb 7, 2026' to YYYYMMDD format.

    Returns None if parsing fails.
    """
    if not date_str:
        return None
    # Handle formats: "Feb 7, 2026", "February 7, 2026", "Feb 7 2026"
    cleaned = date_str.strip().replace(",", "")
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Class listing
# ---------------------------------------------------------------------------

def list_classes() -> list[dict]:
    """List all enrolled classes from the member page."""
    print("Opening member page...", file=sys.stderr)
    _ab_open("https://www.agenticcoding.school/member")

    raw = _ab_eval(LIST_CLASSES_JS)
    try:
        classes = json.loads(_extract_json_array(raw))
    except (json.JSONDecodeError, ValueError):
        print("Warning: Could not parse class list", file=sys.stderr)
        classes = []

    # Deduplicate by URL
    seen = set()
    unique = []
    for c in classes:
        url = c.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(c)

    print(f"Found {len(unique)} classes", file=sys.stderr)
    return unique


def list_lessons(url: str) -> dict:
    """List all lessons for a class, grouped by chapter.

    Navigates to the class page, parses the structure, then clicks each
    lesson to capture its URL (with videoId/chapterId parameters).

    Returns a dict with title, url, and chapters (each with lessons).
    """
    print(f"Opening class: {url}", file=sys.stderr)
    _ab_open(url)
    time.sleep(2)

    raw = _ab_eval(CLASS_STRUCTURE_JS)
    try:
        structure = json.loads(_extract_json_object(raw))
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing class structure: {e}", file=sys.stderr)
        return {"error": str(e), "url": url, "chapters": []}

    class_title = structure.get("title", "Unknown Class")
    chapters = structure.get("chapters", [])
    chapters = [ch for ch in chapters if ch.get("lessons")]

    total_lessons = sum(len(ch["lessons"]) for ch in chapters)
    print(f"Class: {class_title}", file=sys.stderr)
    print(f"Chapters: {len(chapters)}, Lessons: {total_lessons}", file=sys.stderr)

    # Click each lesson to capture the URL with videoId parameter
    lesson_idx = 0
    for chapter in chapters:
        for lesson in chapter["lessons"]:
            _ab_eval(CLICK_LESSON_JS.format(idx=lesson_idx))
            time.sleep(1)
            # Capture URL after click
            current_url = _ab_eval("window.location.href")
            lesson["url"] = current_url
            # Extract videoId from URL
            parsed = urlparse(current_url)
            qs = parse_qs(parsed.query)
            lesson["videoId"] = qs.get("videoId", [None])[0]
            lesson["chapterId"] = qs.get("chapterId", [None])[0]
            lesson_idx += 1

    return {
        "title": class_title,
        "url": url,
        "chapters": chapters,
        "total_lessons": total_lessons,
    }


# ---------------------------------------------------------------------------
# Single class extraction
# ---------------------------------------------------------------------------

def _extract_single_lesson(
    url: str,
    output_dir: Path,
    chapter_name: str = "single",
) -> dict:
    """Extract a single lesson by navigating directly to its URL.

    The URL must contain videoId (and optionally chapterId) parameters.
    """
    print(f"Opening lesson: {url}", file=sys.stderr)
    _ab_open(url)
    time.sleep(3)

    # Get lesson metadata
    meta_raw = _ab_eval(GET_LESSON_META_JS)
    try:
        lesson_page_meta = json.loads(_extract_json_object(meta_raw))
    except (json.JSONDecodeError, ValueError):
        lesson_page_meta = {}

    video_url = lesson_page_meta.get("videoUrl")
    published_date = lesson_page_meta.get("publishedDate")
    lesson_url = lesson_page_meta.get("url", url)

    # Get class structure to find the lesson title and chapter
    raw = _ab_eval(CLASS_STRUCTURE_JS)
    try:
        structure = json.loads(_extract_json_object(raw))
    except (json.JSONDecodeError, ValueError):
        structure = {}

    class_title = structure.get("title", "Unknown Class")

    # Find the active lesson in the structure
    lesson_title = "Unknown Lesson"
    for ch in structure.get("chapters", []):
        for lesson in ch.get("lessons", []):
            if lesson.get("isActive"):
                lesson_title = lesson.get("title", lesson_title)
                chapter_name = ch.get("name", chapter_name)
                break

    lesson_slug = _slugify(lesson_title)
    chapter_slug = _slugify(chapter_name)
    lesson_dir = output_dir / chapter_slug / lesson_slug
    lesson_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Lesson: {chapter_name} / {lesson_title}", file=sys.stderr)

    all_files = []
    all_excalidraws = []

    # Extract Description
    _ab_eval(CLICK_TAB_JS.format(tab_name="Description"))
    time.sleep(1)

    desc_raw = _ab_eval(GET_DESCRIPTION_JS)
    try:
        desc_data = json.loads(_extract_json_object(desc_raw))
    except (json.JSONDecodeError, ValueError):
        desc_data = {"text": "", "links": [], "html": ""}

    desc_links = desc_data.get("links", [])
    desc_text = desc_data.get("text", "")

    excalidraw_links = [
        l for l in desc_links if "excalidraw.com" in l.get("href", "")
    ]
    other_links = [
        l for l in desc_links if "excalidraw.com" not in l.get("href", "")
    ]

    if desc_text.strip():
        desc_md = f"# {lesson_title} - Description\n\n"
        if excalidraw_links:
            desc_md += "## Excalidraw Diagrams\n\n"
            for link in excalidraw_links:
                desc_md += f"- [{link['text']}]({link['href']})\n"
            desc_md += "\n"
        if other_links:
            desc_md += "## Links\n\n"
            for link in other_links:
                desc_md += f"- [{link['text']}]({link['href']})\n"
            desc_md += "\n"
        (lesson_dir / "description.md").write_text(desc_md, encoding="utf-8")
        all_files.append(
            str(lesson_dir.relative_to(output_dir) / "description.md")
        )

    all_excalidraws.extend(
        {"lesson": lesson_title, "chapter": chapter_name, **l}
        for l in excalidraw_links
    )

    # Extract Transcript
    _ab_eval(CLICK_TAB_JS.format(tab_name="Transcript"))
    time.sleep(2)

    transcript_raw = _ab_eval(GET_TRANSCRIPT_JS, timeout=15)
    try:
        transcript_data = json.loads(_extract_json_object(transcript_raw))
    except (json.JSONDecodeError, ValueError):
        transcript_data = {"text": ""}

    transcript_text = transcript_data.get("text", "")
    transcript_md = ""
    if transcript_text and len(transcript_text) > 50:
        parsed = _parse_transcript(transcript_text)
        transcript_md = (
            f"# {lesson_title} - Transcript\n\n"
            f"**Chapter**: {chapter_name}\n\n"
            f"---\n\n{parsed}\n"
        )
        (lesson_dir / "transcript.md").write_text(
            transcript_md, encoding="utf-8"
        )
        all_files.append(
            str(lesson_dir.relative_to(output_dir) / "transcript.md")
        )

    # Write lesson metadata
    lesson_meta = {
        "title": lesson_title,
        "chapter": chapter_name,
        "publishedDate": published_date,
        "videoUrl": video_url,
        "lessonUrl": lesson_url,
        "links": desc_links,
        "excalidraw_links": excalidraw_links,
        "has_transcript": bool(transcript_md),
    }
    (lesson_dir / "metadata.json").write_text(
        json.dumps(lesson_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    all_files.append(
        str(lesson_dir.relative_to(output_dir) / "metadata.json")
    )

    # Write class-level metadata
    class_meta = {
        "success": True,
        "resourceType": "agenticcoding",
        "title": class_title,
        "url": url,
        "total_lessons": 1,
        "lessons": [lesson_meta],
        "excalidraw_links": all_excalidraws,
        "files_created": all_files,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(class_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"  Saved to {lesson_dir}/", file=sys.stderr)
    print(f"  Files created: {len(all_files)}", file=sys.stderr)

    return class_meta


def _is_single_lesson_url(url: str) -> bool:
    """Return True if the URL targets a specific lesson (has videoId param)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return bool(qs.get("videoId"))


def extract_class(
    url: str,
    output_dir: Path,
    since: str | None = None,
) -> dict:
    """Extract lessons from a single class.

    If the URL contains a ``videoId`` parameter, extracts only that lesson.
    If ``since`` is provided (YYYYMMDD format), skips lessons published before
    that date.

    Creates output structure:
        output_dir/
            metadata.json
            {chapter}/{lesson-slug}/
                transcript.md
                description.md    (if non-empty)
                metadata.json
    """
    # Single lesson extraction: URL has videoId parameter
    if _is_single_lesson_url(url):
        return _extract_single_lesson(url, output_dir)

    print(f"Opening class: {url}", file=sys.stderr)
    _ab_open(url)
    time.sleep(2)

    # Get class structure
    raw = _ab_eval(CLASS_STRUCTURE_JS)
    try:
        structure = json.loads(_extract_json_object(raw))
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing class structure: {e}", file=sys.stderr)
        return {"error": str(e), "url": url}

    class_title = structure.get("title", "Unknown Class")
    chapters = structure.get("chapters", [])

    # Filter out empty chapters (like "Outline")
    chapters = [ch for ch in chapters if ch.get("lessons")]

    total_lessons = sum(len(ch["lessons"]) for ch in chapters)
    print(f"Class: {class_title}", file=sys.stderr)
    print(f"Chapters: {len(chapters)}, Lessons: {total_lessons}", file=sys.stderr)
    if since:
        print(f"  --since filter: only lessons from {since} onwards", file=sys.stderr)

    output_dir.mkdir(parents=True, exist_ok=True)

    all_lessons = []
    all_files = []
    all_excalidraws = []
    skipped_count = 0
    lesson_idx = 0  # Global index across all chapters

    for chapter in chapters:
        chapter_name = chapter["name"]
        chapter_slug = _slugify(chapter_name)

        for lesson in chapter["lessons"]:
            lesson_title = lesson["title"]
            lesson_slug = _slugify(lesson_title)
            lesson_dir = output_dir / chapter_slug / lesson_slug
            lesson_dir.mkdir(parents=True, exist_ok=True)

            print(
                f"  [{lesson_idx + 1}/{total_lessons}] "
                f"{chapter_name} / {lesson_title}",
                file=sys.stderr,
            )

            # Click the lesson
            click_raw = _ab_eval(CLICK_LESSON_JS.format(idx=lesson_idx))
            time.sleep(3)

            # --- Extract lesson metadata (video URL, published date) ---
            meta_raw = _ab_eval(GET_LESSON_META_JS)
            try:
                lesson_page_meta = json.loads(_extract_json_object(meta_raw))
            except (json.JSONDecodeError, ValueError):
                lesson_page_meta = {}

            video_url = lesson_page_meta.get("videoUrl")
            published_date = lesson_page_meta.get("publishedDate")
            lesson_url = lesson_page_meta.get("url", "")

            # --- Apply --since filter ---
            if since and published_date:
                parsed_date = _parse_published_date(published_date)
                if parsed_date and parsed_date < since:
                    print(
                        f"    Skipping (published {published_date}, "
                        f"before {since})",
                        file=sys.stderr,
                    )
                    skipped_count += 1
                    lesson_idx += 1
                    continue

            # --- Extract Description (links, excalidraws) ---
            _ab_eval(CLICK_TAB_JS.format(tab_name="Description"))
            time.sleep(1)

            desc_raw = _ab_eval(GET_DESCRIPTION_JS)
            try:
                desc_data = json.loads(_extract_json_object(desc_raw))
            except (json.JSONDecodeError, ValueError):
                desc_data = {"text": "", "links": [], "html": ""}

            desc_links = desc_data.get("links", [])
            desc_text = desc_data.get("text", "")

            # Separate excalidraw links
            excalidraw_links = [
                l for l in desc_links if "excalidraw.com" in l.get("href", "")
            ]
            other_links = [
                l for l in desc_links if "excalidraw.com" not in l.get("href", "")
            ]

            # Write description if non-empty
            if desc_text.strip():
                desc_md = f"# {lesson_title} - Description\n\n"
                if excalidraw_links:
                    desc_md += "## Excalidraw Diagrams\n\n"
                    for link in excalidraw_links:
                        desc_md += f"- [{link['text']}]({link['href']})\n"
                    desc_md += "\n"
                if other_links:
                    desc_md += "## Links\n\n"
                    for link in other_links:
                        desc_md += f"- [{link['text']}]({link['href']})\n"
                    desc_md += "\n"
                (lesson_dir / "description.md").write_text(desc_md, encoding="utf-8")
                all_files.append(
                    str(lesson_dir.relative_to(output_dir) / "description.md")
                )

            all_excalidraws.extend(
                {"lesson": lesson_title, "chapter": chapter_name, **l}
                for l in excalidraw_links
            )

            # --- Extract Transcript ---
            _ab_eval(CLICK_TAB_JS.format(tab_name="Transcript"))
            time.sleep(2)

            transcript_raw = _ab_eval(GET_TRANSCRIPT_JS, timeout=15)
            try:
                transcript_data = json.loads(_extract_json_object(transcript_raw))
            except (json.JSONDecodeError, ValueError):
                transcript_data = {"text": ""}

            transcript_text = transcript_data.get("text", "")
            transcript_md = ""
            if transcript_text and len(transcript_text) > 50:
                parsed = _parse_transcript(transcript_text)
                transcript_md = (
                    f"# {lesson_title} - Transcript\n\n"
                    f"**Chapter**: {chapter_name}\n"
                    f"**Duration**: {lesson.get('duration', '')}\n\n"
                    f"---\n\n{parsed}\n"
                )
                (lesson_dir / "transcript.md").write_text(
                    transcript_md, encoding="utf-8"
                )
                all_files.append(
                    str(lesson_dir.relative_to(output_dir) / "transcript.md")
                )

            # Write per-lesson metadata
            lesson_meta = {
                "title": lesson_title,
                "chapter": chapter_name,
                "duration": lesson.get("duration", ""),
                "publishedDate": published_date,
                "videoUrl": video_url,
                "lessonUrl": lesson_url,
                "links": desc_links,
                "excalidraw_links": excalidraw_links,
                "has_transcript": bool(transcript_md),
            }
            (lesson_dir / "metadata.json").write_text(
                json.dumps(lesson_meta, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            all_files.append(
                str(lesson_dir.relative_to(output_dir) / "metadata.json")
            )

            all_lessons.append(lesson_meta)
            lesson_idx += 1

    extracted_count = len(all_lessons)

    # Write class-level metadata
    class_meta = {
        "success": True,
        "resourceType": "agenticcoding",
        "title": class_title,
        "url": url,
        "chapters": [
            {
                "name": ch["name"],
                "lessons": [l["title"] for l in ch["lessons"]],
            }
            for ch in chapters
        ],
        "total_lessons": total_lessons,
        "extracted_lessons": extracted_count,
        "skipped_lessons": skipped_count,
        "excalidraw_links": all_excalidraws,
        "files_created": all_files,
    }
    if since:
        class_meta["since_filter"] = since

    (output_dir / "metadata.json").write_text(
        json.dumps(class_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"  Saved to {output_dir}/", file=sys.stderr)
    print(f"  Lessons extracted: {extracted_count}/{total_lessons}", file=sys.stderr)
    if skipped_count:
        print(f"  Lessons skipped (--since): {skipped_count}", file=sys.stderr)
    print(f"  Files created: {len(all_files)}", file=sys.stderr)
    if all_excalidraws:
        print(f"  Excalidraw links: {len(all_excalidraws)}", file=sys.stderr)

    return class_meta


# ---------------------------------------------------------------------------
# Adapter class for registry
# ---------------------------------------------------------------------------

class AgenticCodingAdapter:
    """Adapter for agenticcoding.school class content."""

    resource_type = "agenticcoding"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return "agenticcoding.school" in url

    def extract(
        self,
        url: str,
        link_text: str,
        article_dir: Path,
        since: str | None = None,
    ) -> ExtractionResult:
        metadata = extract_class(url, output_dir=article_dir, since=since)
        if metadata.get("error"):
            return ExtractionResult(
                success=False,
                resource_type=self.resource_type,
                error=metadata["error"],
            )
        return ExtractionResult(
            success=True,
            resource_type=self.resource_type,
            files_created=metadata.get("files_created", []),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unknown"
