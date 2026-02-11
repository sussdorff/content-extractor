"""agent-browser CLI helpers."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

SESSION = "extract"
PROFILE = str(Path.home() / ".agent-browser-profiles" / "substack")


def ab(*args: str, timeout: int = 30, profile: str | None = None) -> str:
    """Run an agent-browser command and return stdout."""
    cmd = ["agent-browser", "--session", SESSION]
    if profile or PROFILE:
        cmd.extend(["--profile", profile or PROFILE])
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def ab_open(url: str) -> None:
    """Navigate to a URL."""
    ab("open", url)
    time.sleep(2)


def ab_eval(js: str, timeout: int = 30) -> str:
    """Execute JavaScript and return the result string.

    Uses --stdin to avoid shell quoting issues with complex JS.
    """
    cmd = ["agent-browser", "--session", SESSION]
    if PROFILE:
        cmd.extend(["--profile", PROFILE])
    cmd.extend(["--json", "eval", "--stdin"])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, input=js
    )
    raw = result.stdout.strip()
    # --json wraps result in {"success":true,"data":{"result":"..."}}
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict) and "data" in wrapper:
            return wrapper["data"].get("result", "")
    except (json.JSONDecodeError, TypeError):
        pass
    return raw


def ab_scroll_down(amount: int = 3) -> None:
    """Scroll down by N viewport heights."""
    ab("scroll", "down", str(amount))
    time.sleep(1)


def ab_close() -> None:
    """Close the browser session."""
    try:
        ab("close")
    except Exception:
        pass
