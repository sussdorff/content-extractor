"""Tests for the post-extraction hook system."""

import tempfile
from pathlib import Path

from content_extractor.hooks import (
    HookResult,
    PostExtractionHook,
    _FilteredHook,
    load_hook_from_script,
    load_hooks_from_config,
    run_hooks,
)


class _DummyHook:
    """Test hook that always runs."""
    def should_run(self, metadata: dict, article_dir: Path) -> bool:
        return True

    def run(self, metadata: dict, article_dir: Path) -> HookResult:
        return HookResult(success=True, files_created=["test.md"])


class _ConditionalHook:
    """Test hook that only runs for notion resources."""
    def should_run(self, metadata: dict, article_dir: Path) -> bool:
        return metadata.get("resourceType") == "notion"

    def run(self, metadata: dict, article_dir: Path) -> HookResult:
        return HookResult(success=True, files_created=["notion-processed.md"])


class TestRunHooks:
    def test_runs_applicable_hooks(self):
        hooks = [_DummyHook()]
        results = run_hooks(hooks, {"resourceType": "substack"}, Path("/tmp"))
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].files_created == ["test.md"]

    def test_conditional_hook_runs_when_matching(self):
        hooks = [_ConditionalHook()]
        results = run_hooks(hooks, {"resourceType": "notion"}, Path("/tmp"))
        assert len(results) == 1

    def test_conditional_hook_skips_when_not_matching(self):
        hooks = [_ConditionalHook()]
        results = run_hooks(hooks, {"resourceType": "substack"}, Path("/tmp"))
        assert len(results) == 0

    def test_multiple_hooks(self):
        hooks = [_DummyHook(), _ConditionalHook()]
        results = run_hooks(hooks, {"resourceType": "notion"}, Path("/tmp"))
        assert len(results) == 2

    def test_empty_hooks_list(self):
        results = run_hooks([], {}, Path("/tmp"))
        assert results == []


class TestFilteredHook:
    def test_filters_by_resource_type(self):
        inner = _DummyHook()
        filtered = _FilteredHook(inner, ["notion", "google_drive"])
        assert filtered.should_run({"resourceType": "notion"}, Path("/tmp")) is True
        assert filtered.should_run({"resourceType": "substack"}, Path("/tmp")) is False

    def test_passes_through_to_inner_run(self):
        inner = _DummyHook()
        filtered = _FilteredHook(inner, ["notion"])
        result = filtered.run({"resourceType": "notion"}, Path("/tmp"))
        assert result.success is True


class TestLoadHookFromScript:
    def test_loads_valid_script(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""
from pathlib import Path

class MyHook:
    def should_run(self, metadata, article_dir):
        return True
    def run(self, metadata, article_dir):
        from content_extractor.hooks import HookResult
        return HookResult(success=True, files_created=[])

def hook():
    return MyHook()
""")
            f.flush()
            hook = load_hook_from_script(f.name)
            assert hook.should_run({}, Path("/tmp")) is True

    def test_raises_on_missing_file(self):
        try:
            load_hook_from_script("/nonexistent/hook.py")
            assert False, "Should raise FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_raises_on_missing_factory(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# No hook() function defined\nx = 1\n")
            f.flush()
            try:
                load_hook_from_script(f.name)
                assert False, "Should raise ValueError"
            except ValueError:
                pass


class TestLoadHooksFromConfig:
    def test_returns_empty_when_no_config(self):
        hooks = load_hooks_from_config("/nonexistent/.content-extractor.toml")
        assert hooks == []

    def test_loads_from_toml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write hook script
            hook_path = Path(tmpdir) / "my_hook.py"
            hook_path.write_text("""
from pathlib import Path

class MyHook:
    def should_run(self, metadata, article_dir):
        return True
    def run(self, metadata, article_dir):
        from content_extractor.hooks import HookResult
        return HookResult(success=True, files_created=[])

def hook():
    return MyHook()
""")
            # Write config
            config_path = Path(tmpdir) / ".content-extractor.toml"
            config_path.write_text(f"""
[[hooks]]
script = "./my_hook.py"
""")
            hooks = load_hooks_from_config(config_path)
            assert len(hooks) == 1

    def test_filters_by_resource_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hook_path = Path(tmpdir) / "my_hook.py"
            hook_path.write_text("""
from pathlib import Path

class MyHook:
    def should_run(self, metadata, article_dir):
        return True
    def run(self, metadata, article_dir):
        from content_extractor.hooks import HookResult
        return HookResult(success=True, files_created=[])

def hook():
    return MyHook()
""")
            config_path = Path(tmpdir) / ".content-extractor.toml"
            config_path.write_text(f"""
[[hooks]]
script = "./my_hook.py"
resource_types = ["notion"]
""")
            hooks = load_hooks_from_config(config_path)
            assert len(hooks) == 1
            # Should be wrapped in _FilteredHook
            assert isinstance(hooks[0], _FilteredHook)
