"""Change Localization benchmark via GitHub Models API.

Uses free GitHub Models tokens to test tempograph across multiple models.
Rate limits: GPT-4o = 50 req/day, GPT-4o-mini = 150 req/day.

Usage:
    # GPT-4o-mini (150 req/day budget = ~45 examples × 2 conditions)
    python3 -m bench.changelocal.run_github_models --model openai/gpt-4o-mini --subset 45

    # GPT-4o (50 req/day budget = ~20 examples × 2 conditions)
    python3 -m bench.changelocal.run_github_models --model openai/gpt-4o --subset 20

    # DeepSeek (150 req/day)
    python3 -m bench.changelocal.run_github_models --model deepseek/DeepSeek-V3-0324 --subset 45
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .context import checkout_base, restore_default_branch, get_tempograph_context, model_context_budget, repo_lock
from .evaluate import file_metrics, aggregate
from .run import _build_prompt, _parse_file_list, _prioritize_files, _list_repo_files

GITHUB_API = "https://models.github.ai/inference/chat/completions"
RESULTS_DIR = Path(__file__).parent.parent / "results" / "changelocal"


class RateLimitExhausted(Exception):
    """Daily rate limit hit — stop this model, move to next."""
    pass


def _get_token() -> str:
    """Get GitHub token from env or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    raise RuntimeError("No GitHub token found. Set GITHUB_TOKEN or run `gh auth login`.")


def _call_github_models(prompt: str, model: str, token: str) -> str:
    """Call GitHub Models API with OpenAI-compatible chat/completions."""
    import urllib.request
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
        "seed": 42,
    }).encode()
    req = urllib.request.Request(
        GITHUB_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        if e.code == 429:
            # Check retry-after header
            retry_after = e.headers.get("Retry-After", "")
            if retry_after and int(retry_after) > 300:
                print(f"    [rate limited] daily limit hit — stopping this model")
                raise RateLimitExhausted(f"429: retry-after {retry_after}s")
            wait = min(int(retry_after) if retry_after else 30, 120)
            print(f"    [rate limited] waiting {wait}s...")
            time.sleep(wait)
            return _call_github_models(prompt, model, token)
        print(f"    [API error {e.code}] {body[:200]}")
        return "[]"
    except RateLimitExhausted:
        raise
    except Exception as e:
        print(f"    [error] {e}")
        return "[]"


def run_example(example: dict, condition: str, model: str, token: str) -> dict:
    """Run a single example. condition is 'baseline' or 'tempograph_adaptive_v5_defn'."""
    repo_path = Path(example["repo_path"])

    with repo_lock(repo_path):
        if not checkout_base(repo_path, example["base_sha"]):
            return {"error": "checkout_failed"}

        try:
            file_listing = subprocess.run(
                ["git", "ls-files"], capture_output=True, text=True, cwd=repo_path,
            ).stdout.strip().split("\n")

            task = f"{example['title']}\n{example.get('body', '')}".strip()
            if condition in ("tempograph", "tempograph_adaptive_v5_defn"):
                budget = min(model_context_budget(model), 3000)  # cap for 8K input limit
                context = get_tempograph_context(repo_path, task, max_tokens=budget, definition_first=True)
            else:
                context = ""

            prompt = _build_prompt(task, context, file_listing, prompt_v2=True)

            # Check prompt fits in 8K input limit (~4 chars/token)
            est_tokens = len(prompt) // 4
            if est_tokens > 7500:
                # Trim file listing
                prompt = _build_prompt(task, context, file_listing[:100], prompt_v2=True)

        finally:
            restore_default_branch(repo_path)

    t0 = time.time()
    response = _call_github_models(prompt, model, token)
    duration = time.time() - t0

    predicted = _parse_file_list(response)
    actual = example["files_changed"]
    metrics = file_metrics(predicted, actual)

    return {
        "repo": example["repo"],
        "merge_sha": example["merge_sha"],
        "condition": condition,
        "model": model,
        "task": task[:200],
        "predicted": predicted,
        "actual": actual,
        "duration_s": round(duration, 1),
        "prompt_len": len(prompt),
        "context_injected": bool(context),
        **metrics,
    }


def run_benchmark(
    examples: list[dict],
    model: str,
    token: str,
    outfile: Path,
    skip_shas: set[str] | None = None,
):
    """Run baseline + tempograph conditions for each example."""
    conditions = ("baseline", "tempograph_adaptive_v5_defn")
    total = len(examples) * len(conditions)
    done = 0
    results = []

    with open(outfile, "a") as fh:
        for example in examples:
            if skip_shas and example.get("merge_sha") in skip_shas:
                done += len(conditions)
                continue

            for condition in conditions:
                done += 1
                repo = example["repo"].split("/")[-1]
                print(f"  [{done}/{total}] {repo} | {condition} | {example['title'][:50]}...")
                sys.stdout.flush()

                try:
                    result = run_example(example, condition, model, token)
                except RateLimitExhausted as e:
                    print(f"    [STOP] {e} — saving progress and stopping")
                    return results
                results.append(result)
                fh.write(json.dumps(result) + "\n")
                fh.flush()

                if "error" not in result:
                    print(f"    R={result['recall']:.0%} P={result['precision']:.0%} F1={result['f1']:.0%} ({result['duration_s']}s)")

                # Brief delay between requests (1s is safe for 10-15 rpm limits)
                time.sleep(1)

    return results


def print_report(results: list[dict]):
    """Print comparison report."""
    print("\n" + "=" * 60)
    print("  GitHub Models Benchmark Results")
    print("=" * 60)

    for condition in ("baseline", "tempograph_adaptive_v5_defn"):
        cond_results = [r for r in results if r.get("condition") == condition and "error" not in r]
        if not cond_results:
            continue
        agg = aggregate(cond_results)
        label = "baseline" if condition == "baseline" else "tempograph"
        print(f"\n  {label} (n={agg['n']}):")
        print(f"    F1:        {agg['f1']:.1%}")
        print(f"    Precision: {agg['precision']:.1%}")
        print(f"    Recall:    {agg['recall']:.1%}")

    # Delta
    bl = [r for r in results if r.get("condition") == "baseline" and "error" not in r]
    tg = [r for r in results if r.get("condition") == "tempograph_adaptive_v5_defn" and "error" not in r]
    if bl and tg:
        bl_f1 = sum(r["f1"] for r in bl) / len(bl)
        tg_f1 = sum(r["f1"] for r in tg) / len(tg)
        delta = tg_f1 - bl_f1
        pct = (delta / bl_f1 * 100) if bl_f1 > 0 else 0
        print(f"\n  Delta: {delta:+.3f} F1 ({pct:+.1f}%)")
        print(f"  Model: {results[0].get('model', '?')}")


def main():
    parser = argparse.ArgumentParser(description="Run change-localization bench via GitHub Models API")
    parser.add_argument("--model", default="openai/gpt-4o-mini",
                        help="Model ID (e.g., openai/gpt-4o, openai/gpt-4o-mini, deepseek/DeepSeek-V3-0324)")
    parser.add_argument("--subset", type=int, default=20,
                        help="Number of examples to run (default: 20)")
    parser.add_argument("--examples", default=str(RESULTS_DIR / "examples_n112.jsonl"),
                        help="Path to examples JSONL file")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from existing output file")
    args = parser.parse_args()

    # Load examples
    examples = [json.loads(line) for line in open(args.examples)]
    examples = examples[:args.subset]
    print(f"Loaded {len(examples)} examples from {args.examples}")

    # Token
    token = _get_token()
    print(f"Using model: {args.model}")

    # Output file
    model_slug = args.model.replace("/", "_")
    outfile = RESULTS_DIR / f"github_models_{model_slug}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"

    # Resume support
    skip_shas = set()
    if args.resume:
        existing = list(RESULTS_DIR.glob(f"github_models_{model_slug}_*.jsonl"))
        if existing:
            latest = sorted(existing)[-1]
            outfile = latest
            for line in open(latest):
                d = json.loads(line)
                skip_shas.add(d.get("merge_sha"))
            # Each example has 2 conditions, so count unique merge_shas
            skip_shas_complete = set()
            counts = {}
            for line in open(latest):
                d = json.loads(line)
                sha = d.get("merge_sha")
                counts[sha] = counts.get(sha, 0) + 1
                if counts[sha] >= 2:
                    skip_shas_complete.add(sha)
            skip_shas = skip_shas_complete
            print(f"Resuming from {latest.name}, skipping {len(skip_shas)} completed examples")

    # Budget check
    req_needed = (len(examples) - len(skip_shas)) * 2
    model_name = args.model.split("/")[-1].lower()
    if model_name in ("gpt-4o",):
        daily_limit = 50
    elif "grok-3-mini" in model_name:
        daily_limit = 50
    elif "grok-3" in model_name:
        daily_limit = 30
    else:
        daily_limit = 150
    if req_needed > daily_limit:
        print(f"WARNING: Need {req_needed} requests but daily limit is {daily_limit}.")
        print(f"  Reduce --subset to {daily_limit // 2} or run across multiple days.")

    print(f"Output: {outfile}")
    print(f"Requests needed: {req_needed}")
    print()

    results = run_benchmark(examples, args.model, token, outfile, skip_shas)
    print_report(results)


if __name__ == "__main__":
    main()
