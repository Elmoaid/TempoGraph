"""CrossCodeEval benchmark harness.

Compares code completion quality across three context conditions:
  - no_context: in-file prompt only
  - bm25: CrossCodeEval's default BM25 retrieval
  - tempograph: structural graph context from tempograph

Usage:
    python -m bench.crosscode.run --subset 10        # dry run
    python -m bench.crosscode.run --subset 200       # full run per language
    python -m bench.crosscode.run --conditions tempograph,no_context
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from .evaluate import compute_metrics, aggregate_metrics
from .context import (
    clone_repo,
    get_tempograph_context,
    format_as_crossfile_context,
    extract_query_from_example,
)

RESULTS_DIR = Path(__file__).parent.parent / "results" / "crosscode"
CONDITIONS = ("no_context", "bm25", "tempograph")


DATA_DIR = Path(__file__).parent.parent / "results" / ".cceval_data"
CCEVAL_REPO = "https://github.com/amazon-science/cceval.git"

# Map language names to dataset directory names and JSONL file patterns
LANG_MAP = {
    "python": ("python", "line_completion_rg1_bm25.jsonl"),
    "typescript": ("typescript", "line_completion_rg1_bm25.jsonl"),
    "java": ("java", "line_completion_rg1_bm25.jsonl"),
    "csharp": ("csharp", "line_completion_rg1_bm25.jsonl"),
}


def _ensure_data() -> Path:
    """Clone cceval repo and extract data if needed."""
    import subprocess
    # Data may extract to DATA_DIR directly or to DATA_DIR/crosscodeeval_data
    data_root = DATA_DIR / "crosscodeeval_data"
    if data_root.exists() and any(data_root.iterdir()):
        return data_root
    # Check if extracted directly into DATA_DIR
    if (DATA_DIR / "python").exists():
        return DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    repo_dir = DATA_DIR / "cceval_repo"
    if not repo_dir.exists():
        print("Cloning CrossCodeEval repo...", file=sys.stderr)
        subprocess.run(
            ["git", "clone", "--depth", "1", CCEVAL_REPO, str(repo_dir)],
            check=True, capture_output=True,
        )

    tar_path = repo_dir / "data" / "crosscodeeval_data.tar.xz"
    if tar_path.exists():
        print("Extracting dataset...", file=sys.stderr)
        subprocess.run(
            ["tar", "-xJf", str(tar_path), "-C", str(DATA_DIR)],
            check=True, capture_output=True,
        )
    else:
        print(f"Dataset archive not found at {tar_path}", file=sys.stderr)
        sys.exit(1)

    return data_root


def load_dataset(languages: list[str], subset: int) -> list[dict]:
    """Load CrossCodeEval JSONL data, filter, and sample."""
    import hashlib

    data_root = _ensure_data()
    examples = []

    for lang in languages:
        if lang not in LANG_MAP:
            print(f"Unknown language: {lang}. Available: {list(LANG_MAP.keys())}", file=sys.stderr)
            continue

        lang_dir, jsonl_name = LANG_MAP[lang]
        jsonl_path = data_root / lang_dir / jsonl_name
        if not jsonl_path.exists():
            # Try any available jsonl
            lang_path = data_root / lang_dir
            if lang_path.exists():
                jsonls = list(lang_path.glob("line_completion_rg1*.jsonl"))
                if jsonls:
                    jsonl_path = jsonls[0]
                else:
                    print(f"No JSONL files found for {lang} in {lang_path}", file=sys.stderr)
                    continue
            else:
                print(f"Language directory not found: {lang_path}", file=sys.stderr)
                continue

        print(f"Loading {jsonl_path.name}...", file=sys.stderr)
        items = []
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))

        # Shuffle deterministically, take subset
        items.sort(key=lambda x: hashlib.md5(
            json.dumps(x.get("metadata", {}), sort_keys=True, default=str).encode()
        ).hexdigest())
        taken = items[:subset]
        for item in taken:
            item["_language"] = lang
        examples.extend(taken)
        print(f"Loaded {len(taken)}/{len(items)} {lang} examples", file=sys.stderr)

    return examples


# ── Real-repo benchmark ──────────────────────────────────────────────
# CrossCodeEval repos are anonymized, so we also support a "real repo"
# mode: clone real open-source repos, create completion tasks from them,
# and compare context strategies on those.

REAL_REPOS = [
    ("pallets/flask", "python"),
    ("psf/requests", "python"),
    ("encode/httpx", "python"),
    ("tiangolo/fastapi", "python"),
    ("pydantic/pydantic", "python"),
]


def load_real_repo_dataset(subset: int) -> list[dict]:
    """Create completion tasks from real open-source repos.

    For each repo: clone, run tempograph, then create completion tasks
    by selecting functions and masking their last statement.
    """
    import hashlib
    import re

    examples = []
    for repo_name, lang in REAL_REPOS:
        repo_path = clone_repo(repo_name)
        if not repo_path:
            print(f"  Skip {repo_name} (clone failed)", file=sys.stderr)
            continue

        # Find Python files with functions
        py_files = sorted(repo_path.rglob("*.py"))
        tasks_from_repo = []

        for py_file in py_files:
            rel = str(py_file.relative_to(repo_path))
            if any(skip in rel for skip in ("test", "vendor", "migrations", "__pycache__", ".git")):
                continue
            try:
                content = py_file.read_text(errors="ignore")
            except Exception:
                continue

            lines = content.split("\n")
            if len(lines) < 10:
                continue

            # Find function definitions and create completion tasks
            for i, line in enumerate(lines):
                match = re.match(r'^(\s*)def (\w+)\(', line)
                if not match:
                    continue
                indent = match.group(1)
                func_name = match.group(2)
                if func_name.startswith("_") and func_name != "__init__":
                    continue

                # Find function body end
                body_start = i + 1
                body_end = body_start
                for j in range(body_start, min(len(lines), i + 100)):
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith("#") and not stripped.startswith('"""') and not stripped.startswith("'''"):
                        if lines[j] and not lines[j][0].isspace() and j > body_start + 1:
                            break
                        body_end = j

                if body_end - body_start < 3:
                    continue

                # Mask: prompt = everything up to the last meaningful line
                # groundtruth = the last meaningful line
                cursor_line = body_end
                prompt_text = "\n".join(lines[:cursor_line])
                groundtruth = lines[cursor_line].strip()
                right_context = "\n".join(lines[cursor_line + 1:cursor_line + 10])

                if len(groundtruth) < 5:
                    continue

                task_id = f"{repo_name}/{rel}:{func_name}:{cursor_line}"
                tasks_from_repo.append({
                    "prompt": prompt_text,
                    "groundtruth": groundtruth,
                    "right_context": right_context,
                    "metadata": {
                        "task_id": task_id,
                        "repository": repo_name,
                        "file": rel,
                        "func_name": func_name,
                        "groundtruth_start_lineno": cursor_line,
                    },
                    "crossfile_context": {"text": "", "list": []},
                    "_language": lang,
                    "_repo_path": str(repo_path),
                })

        # Deterministic shuffle, take subset per repo
        tasks_from_repo.sort(key=lambda x: hashlib.md5(x["metadata"]["task_id"].encode()).hexdigest())
        per_repo = max(1, subset // len(REAL_REPOS))
        examples.extend(tasks_from_repo[:per_repo])
        print(f"  {repo_name}: {len(tasks_from_repo)} tasks, using {min(per_repo, len(tasks_from_repo))}", file=sys.stderr)

    return examples


def build_prompt(example: dict, condition: str, tempograph_ctx: str = "") -> str:
    """Build the LLM prompt for a given condition."""
    prompt = example.get("prompt", "")
    right_ctx = example.get("right_context", "")

    if condition == "no_context":
        context_block = ""
    elif condition == "bm25":
        # Use the pre-computed crossfile context from the dataset
        xf = example.get("crossfile_context", {})
        if isinstance(xf, dict) and "text" in xf:
            # cceval format: {"text": "# formatted context...", "list": [...]}
            context_block = xf["text"]
        elif isinstance(xf, str):
            context_block = xf
        else:
            context_block = ""
    elif condition == "tempograph":
        context_block = tempograph_ctx
    else:
        context_block = ""

    # Build the completion prompt
    system = (
        "You are a code completion engine. You output ONLY raw code — the single next line. "
        "NEVER explain. NEVER use markdown. NEVER repeat the prompt. "
        "Output the exact code that replaces <CURSOR>, nothing more."
    )
    user_parts = []
    if context_block:
        user_parts.append(f"Relevant context from other files:\n{context_block}\n")
    user_parts.append(f"{prompt}<CURSOR>\n{right_ctx}")

    return json.dumps({"system": system, "user": "\n".join(user_parts)})


def _clean_completion(text: str) -> str:
    """Strip explanations and markdown from model output, keep only code."""
    import re
    text = text.strip()
    # If model wrapped in ```python ... ```, extract inner
    m = re.search(r'```(?:python|py|typescript|ts|java|csharp)?\s*\n(.+?)```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # If starts with explanation, try to find code after it
    if text and text[0].isalpha() and any(text.startswith(p) for p in
            ("Certainly", "To complete", "Here", "The ", "This ", "Based on", "Looking at", "I ")):
        # Look for a code line after the explanation
        lines = text.split("\n")
        code_lines = []
        in_code = False
        for line in lines:
            stripped = line.strip()
            if not in_code and stripped and not stripped[0].isalpha():
                in_code = True
            if in_code:
                code_lines.append(line)
        if code_lines:
            text = "\n".join(code_lines).strip()
        else:
            # Take just the first line as a guess
            text = lines[0] if lines else text
    # Take only the first meaningful line (completion is single-line)
    lines = [l for l in text.split("\n") if l.strip()]
    return lines[0] if lines else text


async def call_llm(prompt_json: str, model: str = "qwen2.5-coder:32b", ollama_url: str = "http://localhost:11434") -> str:
    """Call LLM for completion. Supports Ollama (default) and Anthropic."""
    import httpx

    prompt = json.loads(prompt_json)

    if model.startswith("claude-"):
        try:
            import anthropic
        except ImportError:
            print("Install anthropic: pip install anthropic", file=sys.stderr)
            sys.exit(1)
        client = anthropic.AsyncAnthropic()
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=256,
                system=prompt["system"],
                messages=[{"role": "user", "content": prompt["user"]}],
            )
            return _clean_completion(response.content[0].text)
        except Exception as e:
            print(f"API error: {e}", file=sys.stderr)
            return ""

    # Ollama
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(f"{ollama_url}/api/chat", json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                "options": {"num_predict": 256, "temperature": 0.1},
            })
            resp.raise_for_status()
            return _clean_completion(resp.json()["message"]["content"])
        except Exception as e:
            print(f"Ollama error: {e}", file=sys.stderr)
            return ""


async def run_condition(
    examples: list[dict],
    condition: str,
    tempograph_contexts: dict[str, str],
    model: str,
    concurrency: int = 3,
    ollama_url: str = "http://localhost:11434",
) -> list[dict]:
    """Run all examples for one condition, return per-example results."""
    semaphore = asyncio.Semaphore(concurrency)
    results = []

    async def process_one(i: int, ex: dict) -> dict:
        async with semaphore:
            task_id = ex.get("metadata", {}).get("task_id", f"unknown_{i}")
            ctx = tempograph_contexts.get(task_id, "") if condition == "tempograph" else ""
            prompt_json = build_prompt(ex, condition, ctx)
            predicted = await call_llm(prompt_json, model, ollama_url)
            reference = ex.get("groundtruth", "")
            metrics = compute_metrics(predicted, reference)
            return {
                "task_id": task_id,
                "condition": condition,
                "language": ex.get("_language", "unknown"),
                "predicted": predicted,
                "reference": reference,
                **metrics,
            }

    tasks = [process_one(i, ex) for i, ex in enumerate(examples)]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        done = len(results)
        if done % 20 == 0 or done == len(examples):
            print(f"  [{condition}] {done}/{len(examples)}", file=sys.stderr)

    return results


def generate_tempograph_contexts(examples: list[dict]) -> dict[str, str]:
    """Pre-generate tempograph context for all examples."""
    contexts = {}
    repos_needed = {}

    for ex in examples:
        meta = ex.get("metadata", {})
        task_id = meta.get("task_id", "")
        repo = meta.get("repository", "")
        file_path = meta.get("file", "")

        # Real-repo examples already have a local path
        local_path = ex.get("_repo_path")
        if local_path and task_id:
            repos_needed.setdefault(repo, []).append((task_id, file_path, ex, Path(local_path)))
        elif repo and task_id:
            repos_needed.setdefault(repo, []).append((task_id, file_path, ex, None))

    print(f"Generating tempograph context for {len(repos_needed)} repos...", file=sys.stderr)
    for repo_name, tasks in repos_needed.items():
        # Use local path from real-repo examples, or clone
        first_local = next((t[3] for t in tasks if t[3]), None)
        if first_local:
            repo_path = first_local
        else:
            repo_path = clone_repo(repo_name)
        if not repo_path:
            print(f"  Skip {repo_name} (clone failed)", file=sys.stderr)
            continue

        print(f"  Indexing {repo_name}...", file=sys.stderr)
        for task_id, file_path, ex, _ in tasks:
            query = extract_query_from_example(ex)
            raw_ctx = get_tempograph_context(repo_path, file_path, query)
            contexts[task_id] = format_as_crossfile_context(raw_ctx)

    print(f"Generated context for {len(contexts)}/{len(examples)} examples", file=sys.stderr)
    return contexts


def main():
    parser = argparse.ArgumentParser(description="CrossCodeEval benchmark for tempograph")
    parser.add_argument("--subset", type=int, default=10, help="Examples per language (default: 10)")
    parser.add_argument("--languages", default="python,typescript", help="Comma-separated languages")
    parser.add_argument("--conditions", default=",".join(CONDITIONS), help="Comma-separated conditions")
    parser.add_argument("--model", default="qwen2.5-coder:32b", help="Model (ollama name or claude-*)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent calls (lower for Ollama)")
    parser.add_argument("--output", default=None, help="Output JSONL path")
    parser.add_argument("--real-repos", action="store_true", help="Use real repos instead of CrossCodeEval dataset")
    args = parser.parse_args()

    languages = [l.strip() for l in args.languages.split(",")]
    conditions = [c.strip() for c in args.conditions.split(",")]

    # Check API key only for Claude models
    if args.model.startswith("claude-") and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    # Load data
    if args.real_repos:
        print(f"Loading real-repo dataset ({args.subset} total)...", file=sys.stderr)
        examples = load_real_repo_dataset(args.subset)
        # Real repos don't have bm25 context, filter it out
        conditions = [c for c in conditions if c != "bm25"]
        if not conditions:
            conditions = ["no_context", "tempograph"]
    else:
        print(f"Loading CrossCodeEval ({args.subset} per language)...", file=sys.stderr)
        examples = load_dataset(languages, args.subset)
    if not examples:
        print("No examples loaded", file=sys.stderr)
        sys.exit(1)

    # Pre-generate tempograph contexts if needed
    tempograph_contexts: dict[str, str] = {}
    if "tempograph" in conditions:
        tempograph_contexts = generate_tempograph_contexts(examples)

    # Run each condition
    all_results = []
    for condition in conditions:
        print(f"\nRunning condition: {condition} ({len(examples)} examples)...", file=sys.stderr)
        start = time.time()
        results = asyncio.run(run_condition(
            examples, condition, tempograph_contexts, args.model, args.concurrency, args.ollama_url,
        ))
        elapsed = time.time() - start
        all_results.extend(results)
        print(f"  Done in {elapsed:.1f}s", file=sys.stderr)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or str(RESULTS_DIR / f"results_{int(time.time())}.jsonl")
    with open(output_path, "w") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")
    print(f"\nResults saved to {output_path}", file=sys.stderr)

    # Print summary
    print("\n" + "=" * 60)
    for condition in conditions:
        cond_results = [r for r in all_results if r["condition"] == condition]
        if not cond_results:
            continue
        agg = aggregate_metrics(cond_results)
        print(f"\n{condition} ({len(cond_results)} examples):")
        print(f"  Exact Match:    {agg['em']:.1%}")
        print(f"  Edit Similarity: {agg['es']:.1%}")
        print(f"  Identifier F1:  {agg['id_f1']:.1%}")

        # Per-language breakdown
        for lang in set(r["language"] for r in cond_results):
            lang_results = [r for r in cond_results if r["language"] == lang]
            lang_agg = aggregate_metrics(lang_results)
            print(f"    {lang}: EM={lang_agg['em']:.1%} ES={lang_agg['es']:.1%} F1={lang_agg['id_f1']:.1%}")

    print("=" * 60)


if __name__ == "__main__":
    main()
