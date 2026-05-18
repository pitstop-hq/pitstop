#!/usr/bin/env python3
"""
query_corpus.py — semantic search over ChromaDB receipts.

Takes a finding or query text, returns matching receipts.

Usage:
    python3 scripts/query_corpus.py "429 without Retry-After"
    python3 scripts/query_corpus.py "retry storm quota exhaustion" --limit 5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieval.embed import pitstop_embed
from retrieval.chroma import get_collection, query_receipts, collection_count


def main():
    parser = argparse.ArgumentParser(description="Query pitstop corpus by semantic similarity.")
    parser.add_argument("query", help="Finding or query text")
    parser.add_argument("--limit", type=int, default=3, help="Number of results (default: 3)")
    parser.add_argument("--min-score", type=float, default=0.0, help="Minimum similarity score")
    args = parser.parse_args()

    collection = get_collection()
    count = collection_count(collection)

    if count == 0:
        print("ERROR: ChromaDB is empty. Run scripts/embed_corpus.py first.")
        sys.exit(1)

    print(f"\nQuerying {count} receipts...")
    print(f"Query: {args.query}\n")

    embedding = pitstop_embed(args.query)
    results = query_receipts(collection, embedding, n_results=args.limit)

    if not results:
        print("No results found.")
        return

    for i, result in enumerate(results):
        score = result["score"]

        if score < args.min_score:
            continue

        meta = result["metadata"]
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[{i+1}] {meta.get('receipt_id', result['id'])}")
        print(f"    Score:  {score:.3f}")
        print(f"    Repo:   {meta.get('repo', 'unknown')}")
        print(f"    Hazard: {meta.get('hazard_class', 'unknown')}")
        print(f"    Pattern: {meta.get('hazard_summary', '')[:120]}")
        print()


if __name__ == "__main__":
    main()
