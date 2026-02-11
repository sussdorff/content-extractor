"""Excalidraw diagram extraction: PNG export + .excalidraw JSON from shared links."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from ..base import ExtractionResult

PROFILE = str(Path.home() / ".agent-browser-profiles" / "excalidraw")
SESSION = "excalidraw"


# ---------------------------------------------------------------------------
# Browser helpers (dedicated session/profile for excalidraw)
# ---------------------------------------------------------------------------

def _ab(*args: str, timeout: int = 30) -> str:
    """Run an agent-browser command with excalidraw profile."""
    cmd = ["agent-browser", "--session", SESSION, "--profile", PROFILE]
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def _ab_eval(js: str, timeout: int = 30) -> str:
    """Execute JavaScript and return the result string."""
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

JOIN_ROOM_JS = """
(() => {
    const btn = document.querySelector('button');
    if (btn && btn.textContent.includes('Join room')) {
        btn.click();
        return JSON.stringify({joined: true});
    }
    return JSON.stringify({joined: false, reason: 'no join button found'});
})()
"""

GET_PAGE_INFO_JS = """
(() => {
    return JSON.stringify({
        url: window.location.href,
        title: document.title.replace(/ — Excalidraw.*$/, ''),
        hasCanvas: !!document.querySelector('canvas.excalidraw__canvas'),
        hasMenu: !!document.querySelector('[data-testid="main-menu-trigger"]'),
        hasJoinButton: !!document.querySelector('button') &&
            document.querySelector('button').textContent.includes('Join room')
    });
})()
"""

# Install the showSaveFilePicker interception using a real WritableStream
INSTALL_SAVE_INTERCEPT_JS = """
(() => {
    window.__exportChunks = [];
    window.__exportFileName = null;
    window.__exportDone = false;

    window.showSaveFilePicker = async function(options) {
        window.__exportFileName = options?.suggestedName || 'export';
        window.__exportChunks = [];
        window.__exportDone = false;

        const writableStream = new WritableStream({
            write(chunk) {
                // Convert Uint8Array to regular array for JSON serialization
                if (chunk instanceof Uint8Array) {
                    window.__exportChunks.push(Array.from(chunk));
                } else if (chunk instanceof Blob) {
                    // Shouldn't happen but handle it
                    chunk.arrayBuffer().then(ab => {
                        window.__exportChunks.push(Array.from(new Uint8Array(ab)));
                    });
                }
            },
            close() {
                window.__exportDone = true;
            }
        });

        return {
            createWritable: async function() { return writableStream; },
            name: options?.suggestedName || 'export'
        };
    };

    return JSON.stringify({installed: true});
})()
"""

OPEN_MENU_JS = """
(() => {
    document.querySelector('[data-testid="main-menu-trigger"]')?.click();
    return JSON.stringify({opened: true});
})()
"""

CLICK_EXPORT_IMAGE_JS = """
(() => {
    const btn = document.querySelector('[data-testid="image-export-button"]');
    if (btn) { btn.click(); return JSON.stringify({clicked: true}); }
    return JSON.stringify({clicked: false});
})()
"""

CLICK_PNG_JS = """
(() => {
    const btn = document.querySelector('button[aria-label="Export to PNG"]');
    if (btn) { btn.click(); return JSON.stringify({clicked: true}); }
    return JSON.stringify({clicked: false});
})()
"""

CLICK_SAVE_TO_FILE_JS = """
(() => {
    const buttons = document.querySelectorAll('[data-testid="dropdown-menu"] button');
    for (const btn of buttons) {
        if (btn.textContent.trim().startsWith('Save to file')) {
            btn.click();
            return JSON.stringify({clicked: true});
        }
    }
    return JSON.stringify({clicked: false});
})()
"""

GET_EXPORT_STATUS_JS = """
(() => {
    return JSON.stringify({
        fileName: window.__exportFileName,
        chunksCount: window.__exportChunks?.length || 0,
        done: window.__exportDone || false,
        totalBytes: (window.__exportChunks || []).reduce((sum, c) => sum + c.length, 0)
    });
})()
"""

# Retrieve chunks as base64 in batches to avoid huge single responses
GET_EXPORT_CHUNK_JS = """
(() => {{
    const chunks = window.__exportChunks || [];
    if ({idx} >= chunks.length) return JSON.stringify({{error: 'index out of range'}});

    // Combine a batch of chunks
    const batch = chunks.slice({idx}, {idx} + {batch_size});
    const totalLen = batch.reduce((s, c) => s + c.length, 0);
    const combined = new Uint8Array(totalLen);
    let offset = 0;
    for (const chunk of batch) {{
        combined.set(new Uint8Array(chunk), offset);
        offset += chunk.length;
    }}

    // Convert to base64
    let binary = '';
    for (let i = 0; i < combined.length; i++) {{
        binary += String.fromCharCode(combined[i]);
    }}
    const b64 = btoa(binary);
    return JSON.stringify({{base64: b64, bytes: combined.length}});
}})()
"""


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _wait_for_export(timeout: int = 30) -> dict:
    """Wait for export to complete and return status."""
    start = time.time()
    while time.time() - start < timeout:
        raw = _ab_eval(GET_EXPORT_STATUS_JS)
        try:
            status = json.loads(raw)
            if status.get("done") and status.get("chunksCount", 0) > 0:
                return status
        except (json.JSONDecodeError, ValueError):
            pass
        time.sleep(1)
    # Return last status even if not done
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnboundLocalError):
        return {"error": "timeout"}


def _retrieve_export_data(chunk_count: int) -> bytes:
    """Retrieve exported binary data from browser in batches."""
    all_data = bytearray()
    batch_size = 3  # Process 3 chunks at a time
    idx = 0

    while idx < chunk_count:
        js = GET_EXPORT_CHUNK_JS.format(idx=idx, batch_size=batch_size)
        raw = _ab_eval(js, timeout=60)
        try:
            result = json.loads(raw)
            if "base64" in result:
                all_data.extend(base64.b64decode(result["base64"]))
            else:
                print(f"  Warning: chunk retrieval error at idx {idx}: {result}", file=sys.stderr)
                break
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Warning: failed to parse chunk at idx {idx}: {e}", file=sys.stderr)
            break
        idx += batch_size

    return bytes(all_data)


def _export_png() -> bytes | None:
    """Export the current Excalidraw scene as PNG via the UI."""
    # Install interception
    _ab_eval(INSTALL_SAVE_INTERCEPT_JS)
    time.sleep(0.5)

    # Open menu -> Export image -> PNG
    _ab_eval(OPEN_MENU_JS)
    time.sleep(0.5)
    _ab_eval(CLICK_EXPORT_IMAGE_JS)
    time.sleep(1)
    _ab_eval(CLICK_PNG_JS)

    # Wait for export
    status = _wait_for_export(timeout=30)
    if not status.get("done") or status.get("chunksCount", 0) == 0:
        print(f"  PNG export did not complete: {status}", file=sys.stderr)
        return None

    print(f"  PNG export: {status['chunksCount']} chunks, {status['totalBytes']} bytes", file=sys.stderr)
    return _retrieve_export_data(status["chunksCount"])


def _export_excalidraw_json() -> bytes | None:
    """Export the current scene as .excalidraw JSON via Save to file."""
    # Install interception
    _ab_eval(INSTALL_SAVE_INTERCEPT_JS)
    time.sleep(0.5)

    # Open menu -> Save to file
    _ab_eval(OPEN_MENU_JS)
    time.sleep(0.5)
    _ab_eval(CLICK_SAVE_TO_FILE_JS)

    # Wait for export
    status = _wait_for_export(timeout=30)
    if not status.get("done") or status.get("chunksCount", 0) == 0:
        print(f"  JSON export did not complete: {status}", file=sys.stderr)
        return None

    print(f"  JSON export: {status['chunksCount']} chunks, {status['totalBytes']} bytes", file=sys.stderr)
    return _retrieve_export_data(status["chunksCount"])


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ExcalidrawAdapter:
    """Adapter for Excalidraw diagram links (link.excalidraw.com / app.excalidraw.com)."""

    resource_type = "excalidraw"

    def can_handle(self, url: str, resource_type: str = "") -> bool:
        return "excalidraw.com" in url

    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult:
        files_created: list[str] = []

        try:
            return self._do_extract(url, link_text, article_dir, files_created)
        finally:
            _ab_close()

    def _do_extract(
        self, url: str, link_text: str, article_dir: Path, files_created: list[str]
    ) -> ExtractionResult:
        print(f"Opening Excalidraw link: {url}", file=sys.stderr)
        _ab_open(url)
        time.sleep(3)

        # Check page state
        raw = _ab_eval(GET_PAGE_INFO_JS)
        try:
            info = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            info = {}

        title = info.get("title", "") or link_text or "Excalidraw Diagram"

        # Join room if needed (shared links show a join dialog)
        if info.get("hasJoinButton"):
            print("  Joining room (read-only)...", file=sys.stderr)
            _ab_eval(JOIN_ROOM_JS)
            time.sleep(5)

            # Re-check page state
            raw = _ab_eval(GET_PAGE_INFO_JS)
            try:
                info = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                info = {}
            title = info.get("title", "") or title

        if not info.get("hasCanvas"):
            return ExtractionResult(
                success=False,
                resource_type=self.resource_type,
                error="Excalidraw canvas not found on page",
            )

        article_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(title)

        # Export PNG
        print("  Exporting PNG...", file=sys.stderr)
        png_data = _export_png()
        if png_data and len(png_data) > 100:
            png_path = article_dir / f"{slug}.png"
            png_path.write_bytes(png_data)
            files_created.append(str(png_path))
            print(f"  Saved PNG: {png_path} ({len(png_data)} bytes)", file=sys.stderr)
        else:
            print("  Warning: PNG export failed or empty", file=sys.stderr)

        # Export .excalidraw JSON
        print("  Exporting .excalidraw JSON...", file=sys.stderr)
        json_data = _export_excalidraw_json()
        if json_data and len(json_data) > 100:
            excalidraw_path = article_dir / f"{slug}.excalidraw"
            excalidraw_path.write_bytes(json_data)
            files_created.append(str(excalidraw_path))
            print(f"  Saved JSON: {excalidraw_path} ({len(json_data)} bytes)", file=sys.stderr)

            # Parse JSON for metadata
            try:
                scene = json.loads(json_data)
                element_count = len(scene.get("elements", []))
                file_count = len(scene.get("files", {}))
            except (json.JSONDecodeError, ValueError):
                element_count = 0
                file_count = 0
        else:
            print("  Warning: .excalidraw JSON export failed or empty", file=sys.stderr)
            element_count = 0
            file_count = 0

        # Write metadata
        metadata = {
            "title": title,
            "url": url,
            "finalUrl": info.get("url", url),
            "resourceType": self.resource_type,
            "elements": element_count,
            "embeddedFiles": file_count,
            "hasPng": any(f.endswith(".png") for f in files_created),
            "hasExcalidraw": any(f.endswith(".excalidraw") for f in files_created),
        }
        meta_path = article_dir / "metadata.json"
        meta_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        files_created.append(str(meta_path))

        if not any(f.endswith(".png") for f in files_created):
            return ExtractionResult(
                success=False,
                resource_type=self.resource_type,
                files_created=files_created,
                error="Failed to export PNG from Excalidraw",
            )

        return ExtractionResult(
            success=True,
            resource_type=self.resource_type,
            files_created=files_created,
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
    return slug or "diagram"
