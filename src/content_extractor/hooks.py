"""Post-extraction hook system.

Hooks allow consumers to run additional processing after content extraction
without coupling the extractor to specific transformation logic.

Three invocation mechanisms:
1. Python API: ``extract_url(url, hooks=[MyHook()])``
2. CLI ``--hook`` flag: ``content-extract url --hook ./my_hook.py``
3. Config file ``.content-extractor.toml`` in CWD
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class HookResult:
    """Result returned by a post-extraction hook."""

    success: bool
    files_created: list[str] = field(default_factory=list)
    error: str | None = None


@runtime_checkable
class PostExtractionHook(Protocol):
    """Hook that runs after successful extraction."""

    def should_run(self, metadata: dict, article_dir: Path) -> bool:
        """Return True if this hook should process the extraction output."""
        ...

    def run(self, metadata: dict, article_dir: Path) -> HookResult:
        """Execute the hook on the extracted content."""
        ...


def load_hook_from_script(script_path: str | Path) -> PostExtractionHook:
    """Load a PostExtractionHook from a Python script.

    The script must define a ``hook()`` factory function that returns
    a ``PostExtractionHook`` instance.

    Args:
        script_path: Path to the hook script (.py file).

    Returns:
        A PostExtractionHook instance.

    Raises:
        FileNotFoundError: If the script doesn't exist.
        ValueError: If the script doesn't define a ``hook()`` function.
    """
    path = Path(script_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Hook script not found: {path}")

    spec = importlib.util.spec_from_file_location(f"_hook_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load hook script: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    factory = getattr(module, "hook", None)
    if factory is None:
        raise ValueError(
            f"Hook script {path.name} must define a hook() factory function"
        )

    instance = factory()
    if not isinstance(instance, PostExtractionHook):
        raise TypeError(
            f"hook() in {path.name} must return a PostExtractionHook "
            f"(got {type(instance).__name__})"
        )
    return instance


def load_hooks_from_config(config_path: str | Path | None = None) -> list[PostExtractionHook]:
    """Load hooks from a ``.content-extractor.toml`` config file.

    Looks in the current working directory if no path is given.

    Config format::

        [[hooks]]
        script = "./scripts/my_hook.py"
        resource_types = ["notion"]  # optional filter

    Args:
        config_path: Explicit path to config file, or None to auto-detect.

    Returns:
        List of loaded hooks (empty if no config found).
    """
    if config_path is None:
        config_path = Path.cwd() / ".content-extractor.toml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return []

    try:
        import tomllib
    except ModuleNotFoundError:
        # Python < 3.11 fallback (shouldn't happen with >=3.12 requirement)
        return []

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    hooks: list[PostExtractionHook] = []
    for hook_cfg in config.get("hooks", []):
        script = hook_cfg.get("script")
        if not script:
            continue

        # Resolve relative paths against config file location
        script_path = config_path.parent / script
        try:
            hook = load_hook_from_script(script_path)
            # Wrap with resource type filter if specified
            resource_types = hook_cfg.get("resource_types")
            if resource_types:
                hook = _FilteredHook(hook, resource_types)
            hooks.append(hook)
        except (FileNotFoundError, ValueError, TypeError) as e:
            print(f"Warning: Failed to load hook {script}: {e}", file=sys.stderr)

    return hooks


class _FilteredHook:
    """Wrapper that adds resource_type filtering to a hook."""

    def __init__(self, inner: PostExtractionHook, resource_types: list[str]) -> None:
        self._inner = inner
        self._resource_types = set(resource_types)

    def should_run(self, metadata: dict, article_dir: Path) -> bool:
        resource_type = metadata.get("resourceType", metadata.get("resource_type", ""))
        if resource_type not in self._resource_types:
            return False
        return self._inner.should_run(metadata, article_dir)

    def run(self, metadata: dict, article_dir: Path) -> HookResult:
        return self._inner.run(metadata, article_dir)


def run_hooks(
    hooks: list[PostExtractionHook],
    metadata: dict,
    article_dir: Path,
) -> list[HookResult]:
    """Execute all applicable hooks and return their results.

    Args:
        hooks: List of hooks to consider.
        metadata: Extraction metadata dict.
        article_dir: Path to the article output directory.

    Returns:
        List of HookResult for hooks that ran.
    """
    results: list[HookResult] = []
    for hook in hooks:
        try:
            if hook.should_run(metadata, article_dir):
                result = hook.run(metadata, article_dir)
                results.append(result)
                if result.files_created:
                    print(
                        f"  [Hook] {type(hook).__name__}: "
                        f"{len(result.files_created)} files created",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"  [Hook] {type(hook).__name__} error: {e}", file=sys.stderr)
            results.append(HookResult(success=False, error=str(e)))
    return results
