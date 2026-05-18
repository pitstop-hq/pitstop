"""
corpus.py — receipt loading and text extraction.

Loads receipts from pitstop-truth (local dev)
or bundled corpus/ directory (Railway production).
"""

import json
import os
from pathlib import Path
from typing import Optional


# Local development path
PITSTOP_TRUTH_DEFAULT = Path.home() / "Development-Projects" / "pitstop-truth"

# Bundled corpus path (relative to this file's parent)
BUNDLED_CORPUS = Path(__file__).parent.parent / "corpus"


def find_receipt_paths(truth_dir: Optional[Path] = None) -> list[Path]:
    """
    Find all receipt.json files.

    Priority:
    1. Explicit truth_dir argument
    2. PITSTOP_TRUTH_DIR environment variable
    3. Local pitstop-truth repo (development)
    4. Bundled corpus/ directory (Railway production)
    """
    # Explicit argument
    if truth_dir:
        return sorted(truth_dir.glob("receipts/**/receipt.json"))

    # Environment variable override
    env_dir = os.environ.get("PITSTOP_TRUTH_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return sorted(p.glob("receipts/**/receipt.json"))

    # Local development path
    if PITSTOP_TRUTH_DEFAULT.exists():
        paths = sorted(PITSTOP_TRUTH_DEFAULT.glob("receipts/**/receipt.json"))
        if paths:
            return paths

    # Bundled corpus fallback (Railway)
    if BUNDLED_CORPUS.exists():
        paths = sorted(BUNDLED_CORPUS.glob("*.json"))
        if paths:
            print(f"Using bundled corpus: {len(paths)} receipts")
            return paths

    return []


def load_receipt(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def receipt_to_text(receipt: dict) -> str:
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
    paths = find_receipt_paths(truth_dir)
    results = []

    for path in paths:
        receipt = load_receipt(path)
        if receipt and receipt.get("id"):
            results.append((receipt, path))

    return results
