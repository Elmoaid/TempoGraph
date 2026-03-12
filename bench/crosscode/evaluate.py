"""CrossCodeEval metrics: Exact Match, Edit Similarity, Identifier F1."""
from __future__ import annotations

import keyword
import re
import tokenize
import io


def exact_match(predicted: str, reference: str) -> float:
    """1.0 if predicted tokens == reference tokens, else 0.0."""
    return 1.0 if _normalize(predicted) == _normalize(reference) else 0.0


def edit_similarity(predicted: str, reference: str) -> float:
    """Token-level edit similarity (1 - normalized Levenshtein distance)."""
    pred_tokens = _tokenize(predicted)
    ref_tokens = _tokenize(reference)
    if not ref_tokens and not pred_tokens:
        return 1.0
    if not ref_tokens or not pred_tokens:
        return 0.0
    dist = _levenshtein(pred_tokens, ref_tokens)
    max_len = max(len(pred_tokens), len(ref_tokens))
    return 1.0 - dist / max_len


def identifier_f1(predicted: str, reference: str) -> dict[str, float]:
    """Precision, recall, F1 for identifiers in predicted vs reference."""
    pred_ids = _extract_identifiers(predicted)
    ref_ids = _extract_identifiers(reference)
    if not ref_ids and not pred_ids:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not ref_ids:
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0}
    if not pred_ids:
        return {"precision": 1.0, "recall": 0.0, "f1": 0.0}
    # Multiset intersection
    common = sum((min(pred_ids.count(x), ref_ids.count(x)) for x in set(ref_ids)))
    precision = common / len(pred_ids) if pred_ids else 0.0
    recall = common / len(ref_ids) if ref_ids else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def compute_metrics(predicted: str, reference: str) -> dict[str, float]:
    """All metrics for one example."""
    id_scores = identifier_f1(predicted, reference)
    return {
        "em": exact_match(predicted, reference),
        "es": edit_similarity(predicted, reference),
        "id_precision": id_scores["precision"],
        "id_recall": id_scores["recall"],
        "id_f1": id_scores["f1"],
    }


def aggregate_metrics(results: list[dict]) -> dict[str, float]:
    """Average numeric metrics across examples."""
    if not results:
        return {}
    numeric_keys = [k for k in ("em", "es", "id_precision", "id_recall", "id_f1")
                    if k in results[0]]
    return {k: sum(r.get(k, 0) for r in results) / len(results) for k in numeric_keys}


# --- internals ---

def _normalize(s: str) -> str:
    """Normalize whitespace for comparison."""
    return " ".join(s.split())


def _tokenize(s: str) -> list[str]:
    """Split into code tokens."""
    return re.findall(r'[a-zA-Z_]\w*|[^\s]', s)


def _extract_identifiers(code: str) -> list[str]:
    """Extract Python/JS identifiers from code string."""
    ids = re.findall(r'\b[a-zA-Z_]\w*\b', code)
    # Filter out Python keywords and common JS keywords
    skip = set(keyword.kwlist) | {
        "const", "let", "var", "function", "return", "if", "else",
        "for", "while", "class", "import", "from", "export", "default",
        "new", "this", "true", "false", "null", "undefined", "async",
        "await", "try", "catch", "throw", "typeof", "instanceof",
    }
    return [i for i in ids if i not in skip]


def _levenshtein(s1: list[str], s2: list[str]) -> int:
    """Token-level Levenshtein distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, t1 in enumerate(s1):
        curr = [i + 1]
        for j, t2 in enumerate(s2):
            cost = 0 if t1 == t2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(s2)]
