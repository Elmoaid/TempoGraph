# Meta-Review — 2026-03-16 (Run 7)

## Root Cause Discovered: TestFeedback Telemetry Contamination

### Problem
`tests/test_mcp_server.py::TestFeedback` was writing real feedback entries to the
live telemetry files on every `pytest` run:

```python
# Before fix — wrote to real ~/.tempograph/global/feedback.jsonl
report_feedback(REPO_PATH, "focus", False, "missing context")
```

- **43 contaminated entries** injected across 92 test runs
- Result: focus mode showed 74% unhelpful rate in pulse alert (ANOMALY 1)
- L3 cross-repo data: focus=19% success rate

This was the source of the false CRITICAL alert in today's pulse scan.

### Fix
```python
# After fix — isolated to tmp_path
def test_feedback_negative(self, monkeypatch, tmp_path):
    monkeypatch.setattr("tempograph.telemetry.CENTRAL_DIR", tmp_path)
    raw = report_feedback(str(tmp_path), "focus", False, "missing context")
```

- Monkeypatches `CENTRAL_DIR` to `tmp_path` — no global store contamination
- Uses `tmp_path` as repo path — no local store contamination
- 43 contaminated entries removed from both global and local feedback.jsonl

### L3 Fired

First ever L3 cross-repo analysis with clean data:

| Mode | Success Rate | Uses |
|------|-------------|------|
| learn | 100% | 7 |
| quality | 100% | 4 |
| hotspots | 100% | 46 |
| blast | 100% | 2 |
| dead | 100% | 8 |
| overview | 100% | 62 |
| **focus** | **19%** | 53 |

Focus mode has a real problem — not test contamination. 53 uses, only ~10 helpful.

### L2 Bias Mitigated

Added `--task-type meta-review` to health check CLI call in scheduled task prompt.
Meta-review sessions will now be tagged correctly and L2 can exclude them from
strategy learning for real task types (debug, feature, orientation).

## System Score

| Dimension | Score | Delta |
|-----------|-------|-------|
| Coverage | 80% | 0% |
| Signal/Noise | 95% | +5% (contamination removed, L3 data now trustworthy) |
| Self-Improvement | 65% | +5% (L3 fired, L2 bias addressed) |

## Next: Focus Mode Investigation (Run 8)

L3 data confirms: focus=19% is a product problem, not a data problem. Priority
next run: understand why focus mode fails on 81% of queries. Key hypotheses:
1. BFS seeds don't match query well for non-symbol queries (file names, concepts)
2. Token budget (4000 default) cuts off before useful context arrives
3. No fallback when seeds are empty or too shallow

## Commits

- fix: isolate TestFeedback from telemetry to prevent focus-mode data contamination
