"""Generate comparison report from benchmark results.

Usage:
    python -m bench.report                           # latest results
    python -m bench.report --file results/crosscode/results_*.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from .crosscode.evaluate import aggregate_metrics

RESULTS_DIR = Path(__file__).parent / "results"


def load_results(path: str) -> list[dict]:
    results = []
    for line in open(path):
        line = line.strip()
        if line:
            results.append(json.loads(line))
    return results


def find_latest_results() -> str | None:
    pattern = str(RESULTS_DIR / "crosscode" / "results_*.jsonl")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def print_crosscode_report(results: list[dict]):
    conditions = sorted(set(r["condition"] for r in results))
    languages = sorted(set(r["language"] for r in results))

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║         CrossCodeEval Benchmark Results                     ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    print(f"Total examples: {len(results)} ({len(results) // len(conditions)} per condition)")
    print(f"Conditions: {', '.join(conditions)}")
    print(f"Languages: {', '.join(languages)}")

    # Overall comparison
    print("\n┌─────────────────┬─────────┬─────────┬─────────┐")
    print("│ Condition       │  EM     │  ES     │  ID-F1  │")
    print("├─────────────────┼─────────┼─────────┼─────────┤")

    baseline_em = None
    for condition in conditions:
        cond_results = [r for r in results if r["condition"] == condition]
        agg = aggregate_metrics(cond_results)
        em, es, f1 = agg["em"], agg["es"], agg["id_f1"]

        delta = ""
        if baseline_em is not None:
            diff = em - baseline_em
            delta = f" ({'+' if diff >= 0 else ''}{diff:.1%})"
        else:
            baseline_em = em

        print(f"│ {condition:<15} │ {em:>5.1%}  │ {es:>5.1%}  │ {f1:>5.1%}  │{delta}")
    print("└─────────────────┴─────────┴─────────┴─────────┘")

    # Per-language breakdown
    for lang in languages:
        print(f"\n  {lang}:")
        print(f"  {'Condition':<15} {'EM':>7} {'ES':>7} {'ID-F1':>7}")
        print(f"  {'─' * 40}")
        for condition in conditions:
            lang_results = [r for r in results if r["condition"] == condition and r["language"] == lang]
            if not lang_results:
                continue
            agg = aggregate_metrics(lang_results)
            print(f"  {condition:<15} {agg['em']:>6.1%} {agg['es']:>6.1%} {agg['id_f1']:>6.1%}")

    # Statistical significance hint
    print("\n  Note: For statistical significance, run with --subset 200+")
    print("  and use paired bootstrap or McNemar's test.")


def main():
    parser = argparse.ArgumentParser(description="Benchmark results report")
    parser.add_argument("--file", default=None, help="Results JSONL file")
    args = parser.parse_args()

    path = args.file or find_latest_results()
    if not path:
        print("No results found. Run a benchmark first:", file=sys.stderr)
        print("  python -m bench.crosscode.run --subset 10", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {path}", file=sys.stderr)
    results = load_results(path)
    if not results:
        print("Empty results file", file=sys.stderr)
        sys.exit(1)

    # Detect benchmark type
    if results[0].get("condition"):
        print_crosscode_report(results)
    else:
        print("Unknown results format", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
