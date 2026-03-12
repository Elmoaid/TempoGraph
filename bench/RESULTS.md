# Benchmark Results

## CrossCodeEval — Code Completion with Structural Context

**Question:** Does injecting tempograph's structural output into an LLM's context improve code completion quality?

### Setup

| Parameter | Value |
|-----------|-------|
| Model | `qwen2.5-coder:32b` (local, Ollama) |
| Examples | 50 (10 per repo) |
| Repos | flask, requests, httpx, fastapi, pydantic |
| Task | Single-line completion (last statement of a function) |
| Conditions | `no_context` (in-file only) vs `tempograph` (in-file + structural graph) |
| Temperature | 0.1 |
| Date | 2026-03-12 |

### Overall Results

| Condition | Exact Match | Edit Similarity | Identifier F1 |
|-----------|:-----------:|:---------------:|:--------------:|
| no_context | 14.0% | 28.5% | 30.8% |
| **tempograph** | **20.0%** | **35.2%** | **35.3%** |
| Delta | **+6.0%** | **+6.7%** | **+4.5%** |

### Per-Repository Breakdown

| Repository | Condition | EM | ES |
|------------|-----------|:--:|:--:|
| pallets/flask | no_context | 60% | 70% |
| | tempograph | 60% | 73% |
| psf/requests | no_context | 0% | 19% |
| | tempograph | **10%** | **25%** |
| encode/httpx | no_context | 10% | 15% |
| | tempograph | 10% | **25%** |
| tiangolo/fastapi | no_context | 0% | 9% |
| | tempograph | **10%** | **20%** |
| pydantic/pydantic | no_context | 0% | 30% |
| | tempograph | **10%** | **33%** |

### What tempograph injects

For each completion task, tempograph provides:
- **Focused subgraph** — the function being completed, its callers, callees, and type signatures (via `render_focused`)
- **Blast radius** — which other files import or depend on the target file (via `render_blast_radius`)

This gives the model cross-file awareness: what calls this function, what types flow in/out, and what breaks if the completion is wrong.

### Metrics

- **Exact Match (EM):** Predicted tokens == reference tokens (strict)
- **Edit Similarity (ES):** 1 - normalized token-level Levenshtein distance
- **Identifier F1:** Precision/recall of identifiers in predicted vs reference

### Reproducing

```bash
pip install -e ".[bench]"
python -m bench.crosscode.run --real-repos --subset 50 \
  --conditions no_context,tempograph \
  --model qwen2.5-coder:32b
python -m bench.report
```

Raw results: [`crosscode_2026-03-12.jsonl`](crosscode_2026-03-12.jsonl)
