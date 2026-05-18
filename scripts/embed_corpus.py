#!/usr/bin/env python3
"""
embed_corpus.py — index all pitstop-truth receipts into ChromaDB.

Run this to build or refresh the ChromaDB index.
Safe to run repeatedly — idempotent.

Usage:
    python3 scripts/embed_corpus.py
    python3 scripts/embed_corpus.py --truth-dir /path/to/pitstop-truth
    python3 scripts/embed_corpus.py --dry-run
"""

import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieval.corpus import load_all_receipts, receipt_to_text, receipt_to_metadata
from retrieval.embed import pitstop_embed_batch
from retrieval.chroma import get_collection, upsert_receipt, collection_count


def main():
    parser = argparse.ArgumentParser(description="Index pitstop-truth receipts into ChromaDB.")
    parser.add_argument("--truth-dir", default=None, help="Path to pitstop-truth repo")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be indexed without writing")
    parser.add_argument("--verbose", action="store_true", help="Show each receipt as it's indexed")
    args = parser.parse_args()

    truth_dir = Path(args.truth_dir).expanduser() if args.truth_dir else None

    print("Loading receipts from pitstop-truth...")
    receipts = load_all_receipts(truth_dir)

    if not receipts:
        print("ERROR: No receipts found. Check pitstop-truth path.")
        sys.exit(1)

    print(f"Found {len(receipts)} receipts")

    if args.dry_run:
        print("\nDry run — receipts that would be indexed:")
        for receipt, path in receipts:
            print(f"  {receipt['id']}")
        print(f"\nTotal: {len(receipts)} receipts")
        return

    print("\nBuilding text representations...")
    texts = []
    ids = []
    metadatas = []

    for receipt, path in receipts:
        receipt_id = receipt["id"]
        text = receipt_to_text(receipt)
        metadata = receipt_to_metadata(receipt)

        ids.append(receipt_id)
        texts.append(text)
        metadatas.append(metadata)

        if args.verbose:
            print(f"  Prepared: {receipt_id}")

    print(f"Generating embeddings for {len(texts)} receipts...")
    print("(This may take 30-60 seconds on first run while model loads)")

    embeddings = pitstop_embed_batch(texts)

    print("Writing to ChromaDB...")
    collection = get_collection()

    for i, receipt_id in enumerate(ids):
        upsert_receipt(
            collection=collection,
            receipt_id=receipt_id,
            embedding=embeddings[i],
            document=texts[i],
            metadata=metadatas[i],
        )
        if args.verbose:
            print(f"  Indexed: {receipt_id}")

    count = collection_count(collection)

    print(f"\n✓ Done. ChromaDB collection: {count} receipts indexed")
    print(f"  Collection: pitstop_receipts_v1")
    print(f"  Location: data/chroma/")


if __name__ == "__main__":
    main()
