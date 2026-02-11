"""Tests for YouTube channel/playlist extraction and --since parsing."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from content_extractor.adapters.youtube import (
    YouTubeAdapter,
    is_channel_or_playlist,
    list_channel_videos,
)
from content_extractor.cli import parse_since


# ---------------------------------------------------------------------------
# is_channel_or_playlist
# ---------------------------------------------------------------------------


class TestIsChannelOrPlaylist:
    def test_handle_url(self):
        assert is_channel_or_playlist("https://www.youtube.com/@indydevdan")

    def test_handle_url_with_path(self):
        assert is_channel_or_playlist("https://www.youtube.com/@indydevdan/videos")

    def test_channel_c_url(self):
        assert is_channel_or_playlist("https://www.youtube.com/c/SomeChannel")

    def test_channel_id_url(self):
        assert is_channel_or_playlist("https://www.youtube.com/channel/UCxyz123")

    def test_playlist_url(self):
        assert is_channel_or_playlist("https://www.youtube.com/playlist?list=PLxyz123")

    def test_single_video_is_not_channel(self):
        assert not is_channel_or_playlist("https://www.youtube.com/watch?v=abc123")

    def test_short_url_is_not_channel(self):
        assert not is_channel_or_playlist("https://youtu.be/abc123")

    def test_bare_youtube_is_not_channel(self):
        assert not is_channel_or_playlist("https://www.youtube.com/")


# ---------------------------------------------------------------------------
# parse_since
# ---------------------------------------------------------------------------


class TestParseSince:
    def test_weeks(self):
        result = parse_since("4w")
        expected = (datetime.now() - timedelta(weeks=4)).strftime("%Y%m%d")
        assert result == expected

    def test_days(self):
        result = parse_since("30d")
        expected = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        assert result == expected

    def test_months(self):
        result = parse_since("3m")
        expected = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        assert result == expected

    def test_iso_date(self):
        assert parse_since("2025-01-15") == "20250115"

    def test_iso_date_no_dashes(self):
        assert parse_since("20250115") == "20250115"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid --since"):
            parse_since("foobar")

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError, match="Invalid --since"):
            parse_since("4x")


# ---------------------------------------------------------------------------
# list_channel_videos (subprocess mocked)
# ---------------------------------------------------------------------------


_FAKE_ENTRIES = [
    {"id": "vid1", "title": "Video One", "upload_date": "20250201", "url": "https://www.youtube.com/watch?v=vid1"},
    {"id": "vid2", "title": "Video Two", "upload_date": "20250115", "webpage_url": "https://www.youtube.com/watch?v=vid2"},
]


class TestListChannelVideos:
    def test_parses_output(self):
        stdout = "\n".join(json.dumps(e) for e in _FAKE_ENTRIES)
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with patch("content_extractor.adapters.youtube.subprocess.run", return_value=fake_proc):
            videos = list_channel_videos("https://www.youtube.com/@test")
        assert len(videos) == 2
        assert videos[0]["id"] == "vid1"
        assert videos[1]["url"] == "https://www.youtube.com/watch?v=vid2"

    def test_empty_on_failure(self):
        fake_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("content_extractor.adapters.youtube.subprocess.run", return_value=fake_proc):
            videos = list_channel_videos("https://www.youtube.com/@test")
        assert videos == []

    def test_dateafter_passed_to_command(self):
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("content_extractor.adapters.youtube.subprocess.run", return_value=fake_proc) as mock_run:
            list_channel_videos("https://www.youtube.com/@test", dateafter="20250101")
        cmd = mock_run.call_args[0][0]
        assert "--dateafter" in cmd
        assert "20250101" in cmd

    def test_constructs_url_from_id(self):
        entry = {"id": "vid3", "title": "Three"}
        stdout = json.dumps(entry)
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with patch("content_extractor.adapters.youtube.subprocess.run", return_value=fake_proc):
            videos = list_channel_videos("https://www.youtube.com/@test")
        assert videos[0]["url"] == "https://www.youtube.com/watch?v=vid3"


# ---------------------------------------------------------------------------
# extract_channel (subprocess mocked end-to-end)
# ---------------------------------------------------------------------------


class TestExtractChannel:
    def test_creates_subdirs_and_summary(self, tmp_path):
        adapter = YouTubeAdapter()

        # Mock list_channel_videos to return two videos
        fake_videos = [
            {"id": "vid1", "title": "Video One", "upload_date": "20250201", "url": "https://www.youtube.com/watch?v=vid1"},
            {"id": "vid2", "title": "Video Two", "upload_date": "20250115", "url": "https://www.youtube.com/watch?v=vid2"},
        ]

        fake_result = MagicMock()
        fake_result.success = True
        fake_result.error = None
        fake_result.files_created = ["main-article.md", "metadata.json"]

        with (
            patch("content_extractor.adapters.youtube.list_channel_videos", return_value=fake_videos),
            patch.object(adapter, "extract", return_value=fake_result),
        ):
            result = adapter.extract_channel(
                "https://www.youtube.com/@test", tmp_path,
            )

        assert result["success"] is True
        assert result["total"] == 2
        assert result["extracted"] == 2
        assert len(result["videos"]) == 2
        assert (tmp_path / "channel-summary.json").exists()

    def test_returns_failure_when_no_videos(self, tmp_path):
        adapter = YouTubeAdapter()

        with patch("content_extractor.adapters.youtube.list_channel_videos", return_value=[]):
            result = adapter.extract_channel(
                "https://www.youtube.com/@test", tmp_path,
            )

        assert result["success"] is False
        assert result["total"] == 0
