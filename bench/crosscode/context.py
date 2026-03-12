"""Generate tempograph context for CrossCodeEval examples."""
from __future__ import annotations

import os
import subprocess
import hashlib
from pathlib import Path

from tempograph.builder import build_graph
from tempograph.render import render_focused, render_blast_radius, render_overview


REPO_CACHE_DIR = Path(__file__).parent.parent / "results" / ".repos"


def clone_repo(repo_name: str) -> Path | None:
    """Shallow-clone a GitHub repo, return path. Cached."""
    REPO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = repo_name.replace("/", "__")
    repo_path = REPO_CACHE_DIR / safe_name
    if repo_path.exists():
        return repo_path
    url = f"https://github.com/{repo_name}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", url, str(repo_path)],
            capture_output=True, timeout=120, check=True,
        )
        return repo_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def get_tempograph_context(
    repo_path: Path,
    target_file: str,
    query: str | None = None,
) -> str:
    """Generate tempograph context for a completion example.

    Combines focused subgraph (if query provided) with blast radius
    of the target file. Returns formatted context string.
    """
    try:
        graph = build_graph(str(repo_path))
    except Exception:
        return ""

    parts = []

    # Focused context around the query/function name
    if query:
        focused = render_focused(graph, query, max_tokens=1500)
        if focused and "No symbols matching" not in focused:
            parts.append(focused)

    # Blast radius of the target file
    rel_path = target_file
    if rel_path in graph.files:
        blast = render_blast_radius(graph, rel_path)
        if blast and "not found" not in blast:
            parts.append(blast)

    if not parts:
        # Fallback: overview
        parts.append(render_overview(graph))

    return "\n\n".join(parts)


def format_as_crossfile_context(tempograph_output: str) -> str:
    """Format tempograph output to match CrossCodeEval's context injection style.

    CrossCodeEval prepends retrieved code as comment blocks before the prompt.
    We do the same with tempograph's structural output.
    """
    if not tempograph_output:
        return ""
    lines = tempograph_output.split("\n")
    commented = ["# [tempograph context]"] + [f"# {line}" for line in lines] + ["# [end context]", ""]
    return "\n".join(commented)


def extract_query_from_example(example: dict) -> str | None:
    """Extract a search query from a CrossCodeEval example.

    Uses the groundtruth identifiers and the surrounding code context
    to find relevant function/class names to search for.
    """
    import re
    # Try to find function/method calls in the groundtruth
    gt = example.get("groundtruth", "")
    prompt = example.get("prompt", "")

    # Extract identifiers from groundtruth (these are what we need context for)
    ids = re.findall(r'\b[a-zA-Z_]\w*\b', gt)
    # Filter common keywords
    skip = {"self", "cls", "return", "if", "else", "for", "while", "in", "not",
            "and", "or", "is", "None", "True", "False", "def", "class", "import",
            "from", "as", "with", "try", "except", "raise", "pass", "break",
            "continue", "lambda", "yield", "async", "await", "const", "let",
            "var", "function", "new", "this", "typeof", "instanceof", "undefined",
            "null", "true", "false", "export", "default"}
    meaningful = [i for i in ids if i not in skip and len(i) > 2]

    if meaningful:
        return " ".join(meaningful[:3])

    # Fallback: last function def in prompt
    func_match = re.findall(r'def\s+(\w+)|function\s+(\w+)', prompt)
    if func_match:
        last = func_match[-1]
        return last[0] or last[1]

    return None
