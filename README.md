# content-extractor

Pluggable content extraction framework for building knowledge pipelines. Extracts articles, transcripts, and documents from various web sources into structured Markdown + JSON output.

## What it does

`content-extractor` is the **Extract** stage of an ETL pipeline for knowledge:

```
Extract (content-extractor)     Transform (your code)        Load (your vault)
┌──────────────────────┐   ┌──────────────────────┐   ┌─────────────────┐
│ content-extract "url"│   │ Post-extraction hooks │   │ Obsidian / etc  │
│   → main-article.md  │──▶│ e.g. split prompts   │──▶│ Structured notes│
│   → metadata.json    │   │ Your transformations  │   │                 │
│   → downloads/       │   │                       │   │                 │
└──────────────────────┘   └──────────────────────┘   └─────────────────┘
```

Given a URL, it auto-detects the source type and extracts the content into a local directory:

- **main-article.md** - The article content in Markdown
- **metadata.json** - Structured metadata (title, author, date, links, quality info)
- **downloads/** - Any linked resources (Notion pages, Drive files, etc.)

## Supported Sources

| Source | Adapter | What it extracts |
|--------|---------|-----------------|
| Substack | `SubstackAdapter` | Articles, archive scraping, resource links |
| Medium | `MediumAdapter` | Articles with paywall dismissal |
| YouTube | `YouTubeAdapter` | Transcripts + metadata via yt-dlp |
| Notion | `NotionAdapter` | Page content (rendered) |
| Google Drive/Docs | `GoogleDriveAdapter` | File downloads (PDF, XLSX, etc.) |
| Any website | `GenericWebAdapter` | Readability-style content extraction |

All adapters use [agent-browser](https://github.com/nichochar/agent-browser) for browser automation (except YouTube which uses `yt-dlp`).

## Installation

```bash
# Clone and install
git clone https://github.com/sussdorff/content-extractor.git
cd content-extractor
uv sync

# Or install from git
uv pip install git+https://github.com/sussdorff/content-extractor.git
```

### Prerequisites

- **Python >= 3.12**
- **[agent-browser](https://github.com/nichochar/agent-browser)** - CLI tool for browser automation (required for most adapters)
- **yt-dlp** - Required only for YouTube transcript extraction (`pip install yt-dlp`)

## Usage

### CLI

```bash
# Extract a single article
content-extract "https://example.com/article"

# Specify output directory
content-extract --output-dir ./my-output "https://example.com/article"

# Extract multiple URLs
content-extract "https://example.com/a" "https://example.com/b"

# From a file (one URL per line)
content-extract --from urls.txt

# Skip linked resource extraction
content-extract --skip-resources "https://example.com/article"

# Run a post-extraction hook
content-extract --hook ./my_hook.py "https://example.com/article"
```

### Python API

```python
from content_extractor.cli import extract_url

# Basic extraction
result = extract_url("https://example.com/article")
print(result["success"])

# With custom output directory
from pathlib import Path
result = extract_url("https://example.com/article", output_dir=Path("./output"))

# With hooks
from content_extractor.hooks import PostExtractionHook, HookResult

class MyHook:
    def should_run(self, metadata: dict, article_dir: Path) -> bool:
        return metadata.get("resourceType") == "notion"

    def run(self, metadata: dict, article_dir: Path) -> HookResult:
        # Your transformation logic here
        return HookResult(success=True, files_created=["transformed.md"])

result = extract_url("https://example.com/article", hooks=[MyHook()])
```

## Post-Extraction Hooks

Hooks let you run additional processing after content extraction without modifying the extractor itself. This is how consumers (like a note-taking pipeline) integrate with the extraction framework.

### Hook Protocol

```python
from content_extractor.hooks import PostExtractionHook, HookResult
from pathlib import Path

class MyHook:
    def should_run(self, metadata: dict, article_dir: Path) -> bool:
        """Return True if this hook should process the output."""
        return True

    def run(self, metadata: dict, article_dir: Path) -> HookResult:
        """Execute the hook."""
        # Process files in article_dir...
        return HookResult(success=True, files_created=["new-file.md"])
```

### Three Ways to Use Hooks

**1. Python API** (programmatic):
```python
result = extract_url("https://...", hooks=[MyHook()])
```

**2. CLI `--hook` flag** (script path):
```bash
content-extract "url" --hook ./my_hook.py
```

The hook script must export a `hook()` factory function:
```python
# my_hook.py
def hook():
    return MyHook()
```

**3. Config file** `.content-extractor.toml` in working directory:
```toml
[[hooks]]
script = "./scripts/my_hook.py"
resource_types = ["notion"]  # optional: only run for specific resource types
```

## Configuration

Create a `.content-extractor.toml` file in your project directory:

```toml
# Default output directory (CLI flag overrides this)
# output_dir = "./output"

# Hooks to run after extraction
[[hooks]]
script = "./scripts/split_prompts_hook.py"
resource_types = ["notion"]

[[hooks]]
script = "./scripts/another_hook.py"
# No resource_types filter = runs for all extractions
```

## Architecture

The framework uses a **registry pattern** with ordered adapters. When extracting a URL:

1. The URL is classified by source type (Substack, Medium, YouTube, etc.)
2. The registry finds the first adapter that can handle it
3. The adapter extracts content and writes output files
4. Any linked resources (Notion pages, Drive files) are dispatched to their respective adapters
5. Post-extraction hooks run on the output

Adapters implement a simple protocol:

```python
class ContentExtractor(Protocol):
    resource_type: str

    def can_handle(self, url: str, resource_type: str) -> bool: ...
    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult: ...
```

### Writing Custom Adapters

```python
from content_extractor.base import ExtractionResult, ExtractorRegistry
from pathlib import Path

class MyAdapter:
    resource_type = "my_source"

    def can_handle(self, url: str, resource_type: str) -> bool:
        return "my-source.com" in url

    def extract(self, url: str, link_text: str, article_dir: Path) -> ExtractionResult:
        # Your extraction logic...
        return ExtractionResult(
            success=True,
            resource_type=self.resource_type,
            files_created=["main-article.md"],
        )
```

## Development

```bash
# Install in dev mode
cd content-extractor
uv sync

# Run tests
uv run pytest

# Run the CLI
content-extract --help
```

## License

MIT
