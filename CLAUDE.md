# content-extractor

Pluggable content extraction framework — the **Extract** stage of a knowledge ETL pipeline.

## Architecture

```
content-extractor (Extract)     consumer (Transform)        vault (Load)
┌──────────────────────┐   ┌──────────────────────┐   ┌─────────────────┐
│ content-extract "url"│   │ Post-extraction hooks │   │ Obsidian / etc  │
│   → main-article.md  │──▶│ e.g. split_prompts   │──▶│ Structured notes│
│   → metadata.json    │   │ Consumer-specific     │   │                 │
└──────────────────────┘   └──────────────────────┘   └─────────────────┘
```

## Package Structure

```
src/content_extractor/
├── __init__.py          # Public API
├── base.py              # Protocol, registry, result dataclass
├── browser.py           # agent-browser CLI wrapper
├── html_utils.py        # HTML→Markdown converter
├── utils.py             # JSON extraction, date/slug utilities
├── registry.py          # Default registry builder
├── cli.py               # Unified CLI (content-extract)
├── hooks.py             # Post-extraction hook system
└── adapters/            # Source-specific adapters
    ├── substack.py      # Substack articles + archive
    ├── notion.py        # Notion pages (content only, no prompt splitting)
    ├── drive.py         # Google Drive/Docs downloads
    ├── medium.py        # Medium articles
    ├── youtube.py       # YouTube transcripts via yt-dlp
    ├── generic_web.py   # Fallback web extraction
    └── catalog.py       # Metadata-only cataloging
```

## Key Decisions

- **Zero third-party Python deps**: All adapters use stdlib + subprocess to `agent-browser` CLI
- **Protocol-based**: `ContentExtractor` is a Protocol, adapters don't inherit from a base class
- **Hook system**: Post-extraction hooks allow consumers to transform output without coupling
- **NotionAdapter**: Extracts content only — prompt splitting is a consumer-side hook concern

## Development

```bash
uv sync                      # Install in dev mode
content-extract --help       # CLI
uv run pytest                # Tests
```

## Configuration

- `.content-extractor.toml` in CWD for per-project hook config
- `--hook` CLI flag for ad-hoc hooks
- Python API for programmatic usage with `extract_url(url, hooks=[...])`
