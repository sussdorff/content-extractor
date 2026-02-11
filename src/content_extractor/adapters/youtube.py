"""YouTube transcript extraction via yt-dlp."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ..base import ExtractionResult


class YouTubeAdapter:
    resource_type = "youtube"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return "youtu.be" in url or "youtube.com" in url

    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult:
        # Check yt-dlp availability
        try:
            subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True, text=True, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error="yt-dlp is not installed or not working",
            )

        # Fetch metadata + auto-subs in one call
        try:
            proc = subprocess.run(
                [
                    "yt-dlp",
                    "--write-auto-subs", "--sub-lang", "en",
                    "--skip-download", "--print-json",
                    "--paths", str(article_dir),
                    url,
                ],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error="yt-dlp timed out",
            )

        if proc.returncode != 0:
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error=f"yt-dlp failed: {proc.stderr.strip()[:200]}",
            )

        meta = json.loads(proc.stdout)

        title = meta.get("title", link_text or "Untitled")
        channel = meta.get("channel", meta.get("uploader", ""))
        upload_date = meta.get("upload_date", "")
        duration = meta.get("duration_string", "")
        description = meta.get("description", "")

        transcript = _read_subtitle_file(article_dir)

        lines = [f"# {title}\n"]
        if channel:
            lines.append(f"**Channel:** {channel}  ")
        if upload_date:
            formatted = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}" if len(upload_date) == 8 else upload_date
            lines.append(f"**Date:** {formatted}  ")
        if duration:
            lines.append(f"**Duration:** {duration}  ")
        lines.append(f"**URL:** {url}\n")

        if description:
            lines.append("## Description\n")
            lines.append(description + "\n")

        if transcript:
            lines.append("## Transcript\n")
            lines.append(transcript + "\n")

        files_created: list[str] = []

        md_path = article_dir / "main-article.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")
        files_created.append(str(md_path))

        metadata = {
            "title": title,
            "channel": channel,
            "uploadDate": upload_date,
            "duration": duration,
            "url": url,
            "resourceType": self.resource_type,
            "hasTranscript": bool(transcript),
        }
        meta_path = article_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        files_created.append(str(meta_path))

        note = None if transcript else "No transcript available"
        return ExtractionResult(
            success=True, resource_type=self.resource_type,
            files_created=files_created, note=note,
        )


def _read_subtitle_file(directory: Path) -> str:
    """Find and parse the first .vtt or .srt subtitle file in *directory*."""
    for pattern in ("*.en.vtt", "*.vtt", "*.en.srt", "*.srt"):
        files = list(directory.glob(pattern))
        if files:
            raw = files[0].read_text(encoding="utf-8", errors="replace")
            return _parse_vtt(raw) if files[0].suffix == ".vtt" else _parse_srt(raw)
    return ""


def _parse_vtt(text: str) -> str:
    """Extract plain text from a WebVTT file, deduplicating rolling captions."""
    seen: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}", line) and "-->" in line:
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and (not seen or clean != seen[-1]):
            seen.append(clean)
    return "\n".join(seen)


def _parse_srt(text: str) -> str:
    """Extract plain text from an SRT file."""
    lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if re.match(r"^\d+$", line.strip()):
            continue
        if re.match(r"^\d{2}:\d{2}", line) and "-->" in line:
            continue
        clean = line.strip()
        if clean and (not lines or clean != lines[-1]):
            lines.append(clean)
    return "\n".join(lines)
