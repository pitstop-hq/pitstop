#!/usr/bin/env python3
"""
rebuild_index.py — nuclear rebuild of ChromaDB from pitstop-truth.

Drops the existing collection and rebuilds from scratch.
Run when:
  - Something goes wrong with the index
  - Embedding model changes
  - Collection is corrupted
  - Major corpus restructuring

Usage:
    python3 scripts/rebuild_index.py
    python3 scripts/rebuild_index.py --yes  (skip confirmation)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieval.chroma import get_client, COLLECTION_NAME


def main():
    parser = argparse.ArgumentParser(description="Nuclear rebuild of ChromaDB index.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.yes:
        print(f"This will DELETE and rebuild collection: {COLLECTION_NAME}")
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return

    print(f"Dropping collection: {COLLECTION_NAME}")
    client = get_client()

    try:
        client.delete_collection(COLLECTION_NAME)
        print("Collection dropped.")
    except Exception as e:
        print(f"Collection did not exist or could not be dropped: {e}")

    print("Rebuilding from pitstop-truth...")
    print("Running embed_corpus.py...")

    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/embed_corpus.py"],
        cwd=Path(__file__).parent.parent,
    )

    if result.returncode == 0:
        print("\n✓ Rebuild complete.")
    else:
        print("\n✗ Rebuild failed. Check embed_corpus.py output.")
        sys.exit(1)


if __name__ == "__main__":
    main()
