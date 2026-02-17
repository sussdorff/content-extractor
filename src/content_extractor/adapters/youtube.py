"""YouTube transcript extraction via yt-dlp."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from ..base import ExtractionResult

_CHANNEL_PATTERNS = re.compile(
    r"youtube\.com/(@[\w.-]+|c/[\w.-]+|channel/[\w-]+)"
)
_PLAYLIST_PATTERN = re.compile(r"youtube\.com/playlist\?list=")


def is_channel_or_playlist(url: str) -> bool:
    """Return True if *url* points to a YouTube channel or playlist."""
    return bool(_CHANNEL_PATTERNS.search(url) or _PLAYLIST_PATTERN.search(url))


def list_channel_videos(
    url: str, dateafter: str | None = None, limit: int = 50,
) -> list[dict]:
    """Fetch video metadata from a channel/playlist via yt-dlp.

    Returns a list of dicts with keys: id, title, upload_date, url.
    """
    cmd = [
        "yt-dlp", "--dump-json", "--skip-download",
        "--no-warnings",
        "--remote-components", "ejs:github",
        "--playlist-items", f"1-{limit}",
    ]
    if dateafter:
        cmd += ["--dateafter", dateafter]
    cmd.append(url)

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    # yt-dlp may return non-zero but still output valid JSON on stdout
    if not proc.stdout.strip():
        return []

    videos = []
    for line in proc.stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        videos.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", ""),
            "upload_date": entry.get("upload_date", ""),
            "url": entry.get("url") or entry.get("webpage_url")
                   or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
        })
    return videos


class YouTubeAdapter:
    resource_type = "youtube"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return "youtu.be" in url or "youtube.com" in url

    def extract_channel(
        self,
        url: str,
        output_dir: Path,
        dateafter: str | None = None,
        force: bool = False,
    ) -> dict:
        """Extract transcripts from all recent videos on a channel/playlist.

        Args:
            url: Channel or playlist URL.
            output_dir: Base directory for per-video subdirectories.
            dateafter: Optional ``YYYYMMDD`` date filter for yt-dlp.
            force: If True, re-extract even if output already exists.

        Returns:
            Summary dict with channel info and per-video results.
        """
        print(f"  Fetching video list from {url} ...", file=sys.stderr)
        videos = list_channel_videos(url, dateafter=dateafter)
        if not videos:
            return {
                "success": False,
                "error": "No videos found (or yt-dlp failed)",
                "channel": url,
                "videos": [],
                "total": 0,
                "extracted": 0,
                "skipped": 0,
            }

        print(f"  Found {len(videos)} videos, extracting ...", file=sys.stderr)
        results: list[dict] = []
        skipped = 0
        for i, video in enumerate(videos, 1):
            vid_url = video["url"]
            slug = f"youtube-{video['id']}" if video.get("id") else f"youtube-{i}"
            vid_dir = output_dir / slug

            # Skip already-extracted videos unless --force
            if not force and (vid_dir / "main-article.md").exists():
                print(f"  [{i}/{len(videos)}] [skip] {video.get('title', vid_url)}", file=sys.stderr)
                skipped += 1
                results.append({
                    "id": video["id"],
                    "title": video.get("title", ""),
                    "url": vid_url,
                    "success": True,
                    "skipped": True,
                    "error": None,
                    "files_created": [],
                })
                continue

            vid_dir.mkdir(parents=True, exist_ok=True)

            print(f"  [{i}/{len(videos)}] {video.get('title', vid_url)}", file=sys.stderr)
            result = self.extract(vid_url, video.get("title", ""), vid_dir)
            results.append({
                "id": video["id"],
                "title": video.get("title", ""),
                "url": vid_url,
                "success": result.success,
                "error": result.error,
                "files_created": result.files_created,
            })

        extracted_count = sum(1 for r in results if r["success"] and not r.get("skipped"))
        summary = {
            "success": extracted_count > 0 or skipped > 0,
            "channel": url,
            "videos": results,
            "total": len(videos),
            "extracted": extracted_count,
            "skipped": skipped,
        }

        # Write channel summary
        summary_path = output_dir / "channel-summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        skip_msg = f", {skipped} skipped" if skipped else ""
        print(
            f"  Channel done: {extracted_count}/{len(videos)} videos extracted{skip_msg}",
            file=sys.stderr,
        )
        return summary

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
                    "--remote-components", "ejs:github",
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

        # yt-dlp may exit non-zero even when metadata was fetched successfully
        # (e.g. subtitle download 429, n-challenge warnings). Try parsing stdout
        # before giving up.
        meta = None
        if proc.stdout.strip():
            try:
                meta = json.loads(proc.stdout)
            except json.JSONDecodeError:
                pass

        if meta is None:
            return ExtractionResult(
                success=False, resource_type=self.resource_type,
                error=f"yt-dlp failed: {proc.stderr.strip()[:200]}",
            )

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
