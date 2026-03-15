# Tempo

Agent effectiveness engine. Python 3.11+, tree-sitter kernel, plugin architecture.

## Commands

```bash
pip install -e .            # Install (editable)
pip install -e ".[dev]"     # Install with test deps
pip install -e ".[bench]"   # Install with benchmark deps
pytest                      # Run tests
```

## Architecture

```
tempograph/                  ← current (being restructured to tempo/)
  __main__.py   — CLI entry point, arg parsing, mode dispatch, feedback subcommand
  builder.py    — build_graph(): orchestrates parsing + caching
  parser.py     — tree-sitter extraction (35 methods, 7 languages)
  cache.py      — content-hashed snapshot storage (.tempograph/cache.json)
  render.py     — all mode renderers + dead code confidence scoring
  types.py      — Symbol, Edge, Tempo, FileInfo dataclasses
  git.py        — git diff helpers for diff_context mode
  server.py     — MCP server (tempograph-server)
  telemetry.py  — usage + feedback JSONL logging (local + ~/.tempograph/global/)
  report.py     — usage/feedback report generator (filters internal stats noise)
```

## Key Patterns

- All modes share one `Tempo` — build once, render many views
- Cache is content-hashed (not timestamp), so branch-switching is free
- `parser.py` has per-language handlers: `_handle_python_*`, `_handle_js_ts_*`, etc.
- `parser.py` detects dynamic `import()` via regex after tree-sitter walk (for React.lazy, import().then)
- `render.py` functions are `render_<mode>(graph, ...) -> str`
- Token budgets controlled via tiktoken; `--max-tokens` caps focus/diff output
- Dead code confidence scoring penalizes single-component files (-20, likely lazy-loaded)
- `find_dead_code()` checks both cross-file AND same-file references before flagging
- Telemetry writes to both local `.tempograph/` and `~/.tempograph/global/`
- `lazy` is NOT in `_BUILTIN_IGNORE` — removed so lazy() calls produce edges
- `_scan_calls()` traverses `spread_element` nodes (for Zustand-style `...createSlice()`)

## Entry Points

- CLI: `tempograph.__main__:main`
- Feedback: `python3 -m tempograph feedback <repo> <mode> <true|false> [note]`
- MCP server: `tempograph.server:run_server`
- Python API: `from tempograph import build_graph, Tempo`

## Roadmap

See `.claude.local.md` for full roadmap. Currently in Phase 1: Plugin Kernel restructure.
