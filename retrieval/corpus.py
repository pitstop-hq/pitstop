"""
corpus.py — receipt loading and text extraction.

Loads receipts from pitstop-truth and builds
the text representation used for embedding.
"""

import json
from pathlib import Path
from typing import Optional


PITSTOP_TRUTH_DEFAULT = Path.home() / "Development-Projects" / "pitstop-truth"


def find_receipt_paths(truth_dir: Optional[Path] = None) -> list[Path]:
    """
    Find all receipt.json files in pitstop-truth.
    """
    root = truth_dir or PITSTOP_TRUTH_DEFAULT
    return sorted(root.glob("receipts/**/receipt.json"))


def load_receipt(path: Path) -> Optional[dict]:
    """
    Load and parse a single receipt.json.
    Returns None if invalid.
    """
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def receipt_to_text(receipt: dict) -> str:
    """
    Convert a receipt to a text representation for embedding.

    The text should capture:
    - what the failure was
    - what pattern it represents
    - what the fix looks like
    - tags for retrieval
    """
    parts = []

    receipt_id = receipt.get("id", "")
    if receipt_id:
        parts.append(f"Receipt: {receipt_id}")

    hazard = receipt.get("hazard", {})
    summary = hazard.get("summary", "")
    if summary:
        parts.append(f"Pattern: {summary}")

    signals = hazard.get("signals", [])
    if signals:
        parts.append("Signals: " + "; ".join(signals[:3]))

    constraints = receipt.get("constraints", [])
    if constraints:
        parts.append("Constraints: " + "; ".join(constraints[:3]))

    knobs = receipt.get("knobs", [])
    if knobs:
        parts.append("Fix knobs: " + "; ".join(knobs[:3]))

    tags = receipt.get("tags", [])
    if tags:
        parts.append("Tags: " + ", ".join(tags))

    source = receipt.get("source", {})
    repo = source.get("repo", "")
    if repo:
        parts.append(f"Repo: {repo}")

    notes = source.get("notes", "")
    if notes:
        parts.append(f"Notes: {notes[:300]}")

    return "\n".join(parts)


def receipt_to_metadata(receipt: dict) -> dict:
    """
    Extract metadata fields for ChromaDB storage.
    ChromaDB metadata values must be str, int, float, or bool.
    """
    hazard = receipt.get("hazard", {})
    source = receipt.get("source", {})

    hazard_classes = hazard.get("class", [])
    tags = receipt.get("tags", [])

    return {
        "receipt_id": receipt.get("id", ""),
        "created_at": receipt.get("created_at", ""),
        "repo": source.get("repo", ""),
        "source_url": source.get("url", ""),
        "hazard_summary": hazard.get("summary", "")[:500],
        "hazard_class": hazard_classes[0] if hazard_classes else "unknown",
        "tags": ",".join(tags[:10]),
        "schema_version": receipt.get("schema_version", "receipt.v0"),
    }


def load_all_receipts(truth_dir: Optional[Path] = None) -> list[tuple[dict, Path]]:
    """
    Load all receipts from pitstop-truth.
    Returns list of (receipt_dict, path) tuples.
    """
    paths = find_receipt_paths(truth_dir)
    results = []

    for path in paths:
        receipt = load_receipt(path)
        if receipt and receipt.get("id"):
            results.append((receipt, path))

    return results
