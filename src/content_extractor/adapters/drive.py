"""Google Drive / Docs file download via direct export URLs."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..base import ExtractionResult
from ..browser import ab_eval, ab_open


# Patterns to extract document/file IDs from various Google URLs
_DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_SLIDE_ID_RE = re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)")
_DRIVE_FILE_ID_RE = re.compile(r"/file/d/([a-zA-Z0-9_-]+)")


def _extract_id(url: str, pattern: re.Pattern[str]) -> str | None:
    m = pattern.search(url)
    return m.group(1) if m else None


class GoogleDriveAdapter:
    """Download files/folders from Google Drive using direct export URLs."""

    resource_type = "google_drive"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return "drive.google.com" in url or "docs.google.com" in url

    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult:
        print(f"  [Drive] Extracting: {url}", file=sys.stderr)
        try:
            downloads_dir = article_dir / "prompts" / "downloads"
            downloads_dir.mkdir(parents=True, exist_ok=True)

            if "/folders/" in url:
                return self._download_folder(url, downloads_dir)

            export_url = self._build_export_url(url)
            if export_url:
                return self._download_via_export(export_url, url, downloads_dir)

            # Fallback for unrecognized Drive URLs
            return self._download_via_ui(url, downloads_dir)

        except Exception as e:
            print(f"  [Drive] Error: {e}", file=sys.stderr)
            return ExtractionResult(
                success=False, resource_type=self.resource_type, error=str(e),
            )

    def _build_export_url(self, url: str) -> str | None:
        """Build a direct export URL from a Google Docs/Sheets/Slides URL."""
        doc_id = _extract_id(url, _DOC_ID_RE)
        if doc_id:
            return f"https://docs.google.com/document/d/{doc_id}/export?format=pdf"

        sheet_id = _extract_id(url, _SHEET_ID_RE)
        if sheet_id:
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"

        slide_id = _extract_id(url, _SLIDE_ID_RE)
        if slide_id:
            return f"https://docs.google.com/presentation/d/{slide_id}/export?format=pptx"

        file_id = _extract_id(url, _DRIVE_FILE_ID_RE)
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"

        return None

    def _download_via_export(self, export_url: str, original_url: str, downloads_dir: Path) -> ExtractionResult:
        """Navigate to the direct export URL to trigger download, then collect."""
        print(f"  [Drive] Export URL: {export_url}", file=sys.stderr)
        ab_open(export_url)
        time.sleep(5)

        # Google may show a "virus scan" interstitial for large files
        ab_eval("""
            (() => {
                const btn = document.querySelector('#uc-download-link, a[href*="confirm="]');
                if (btn) { btn.click(); return 'confirmed'; }
                return 'no interstitial';
            })()
        """, timeout=10)
        time.sleep(5)

        home_downloads = Path.home() / "Downloads"
        files_created = self._collect_downloads(home_downloads, downloads_dir)

        if files_created:
            return ExtractionResult(
                success=True, resource_type=self.resource_type,
                files_created=files_created, note="exported via direct URL",
            )

        return ExtractionResult(
            success=False, resource_type=self.resource_type,
            error=f"Export download not found in ~/Downloads for {original_url}",
        )

    def _download_folder(self, url: str, downloads_dir: Path) -> ExtractionResult:
        """Download entire Drive folder via UI (no direct export for folders)."""
        ab_open(url)
        time.sleep(3)

        ab_eval("""
            (() => {
                const btns = [...document.querySelectorAll(
                    '[data-tooltip*="ownload"], [aria-label*="ownload"]'
                )];
                if (btns.length) { btns[0].click(); return 'clicked'; }
                const kebab = document.querySelector('[data-tooltip="More actions"]');
                if (kebab) kebab.click();
                return 'menu';
            })()
        """, timeout=10)
        time.sleep(2)

        ab_eval("""
            (() => {
                const items = [...document.querySelectorAll('[role="menuitem"]')];
                const dl = items.find(i => i.textContent.includes('Download'));
                if (dl) dl.click();
                return dl ? 'clicked' : 'not found';
            })()
        """, timeout=10)
        time.sleep(10)

        home_downloads = Path.home() / "Downloads"
        files_created = self._collect_downloads(home_downloads, downloads_dir)

        return ExtractionResult(
            success=len(files_created) > 0, resource_type=self.resource_type,
            files_created=files_created,
            note="folder download" if files_created else "folder download may have failed",
        )

    def _download_via_ui(self, url: str, downloads_dir: Path) -> ExtractionResult:
        """Fallback: try UI-based download for unrecognized Drive URLs."""
        ab_open(url)
        time.sleep(3)

        ab_eval("""
            (() => {
                const btns = [...document.querySelectorAll(
                    '[data-tooltip*="ownload"], [aria-label*="ownload"],'
                    + ' a[href*="export"], a[href*="download"]'
                )];
                if (btns.length) { btns[0].click(); return 'clicked'; }
                const kebab = document.querySelector('[data-tooltip="More actions"]');
                if (kebab) kebab.click();
                return 'menu';
            })()
        """, timeout=10)
        time.sleep(2)

        ab_eval("""
            (() => {
                const items = [...document.querySelectorAll('[role="menuitem"]')];
                const dl = items.find(i => i.textContent.includes('Download'));
                if (dl) dl.click();
                return dl ? 'clicked' : 'not found';
            })()
        """, timeout=10)
        time.sleep(8)

        home_downloads = Path.home() / "Downloads"
        files_created = self._collect_downloads(home_downloads, downloads_dir)

        return ExtractionResult(
            success=len(files_created) > 0, resource_type=self.resource_type,
            files_created=files_created,
            note="UI download" if files_created else "UI download may have failed",
        )

    def _collect_downloads(self, src_dir: Path, dest_dir: Path) -> list[str]:
        """Move recent downloads from ~/Downloads to article dir, unzip if needed."""
        files_created: list[str] = []
        cutoff = time.time() - 60

        for f in sorted(src_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.stat().st_mtime < cutoff:
                break
            if f.name.startswith(".") or f.name == ".DS_Store":
                continue

            if f.suffix == ".zip":
                extract_to = dest_dir / f.stem
                extract_to.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["unzip", "-q", "-o", str(f), "-d", str(extract_to)],
                    capture_output=True, timeout=30,
                )
                macosx = extract_to / "__MACOSX"
                if macosx.exists():
                    shutil.rmtree(macosx)
                f.unlink()
                for child in extract_to.rglob("*"):
                    if child.is_file() and not child.name.startswith("."):
                        files_created.append(str(child))
                print(f"  [Drive] Unzipped to {extract_to.name}/", file=sys.stderr)
            else:
                dest = dest_dir / f.name
                shutil.move(str(f), str(dest))
                files_created.append(str(dest))
                print(f"  [Drive] Saved {f.name}", file=sys.stderr)

            break  # Only handle the most recent file

        return files_created
