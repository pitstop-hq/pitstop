#!/usr/bin/env python3
"""
build_index.py — build ChromaDB index on Railway startup.
Run before uvicorn starts.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieval.corpus import load_all_receipts, receipt_to_text, receipt_to_metadata
from retrieval.embed import pitstop_embed_batch
from retrieval.chroma import get_collection, upsert_receipt, collection_count

def main():
    collection = get_collection()
    existing = collection_count(collection)
    
    if existing > 0:
        print(f"ChromaDB already has {existing} receipts. Skipping rebuild.")
        return

    print("Building ChromaDB index from corpus...")
    receipts = load_all_receipts()
    
    if not receipts:
        print("WARNING: No receipts found.")
        return

    texts = [receipt_to_text(r) for r, _ in receipts]
    ids = [r["id"] for r, _ in receipts]
    metadatas = [receipt_to_metadata(r) for r, _ in receipts]

    embeddings = pitstop_embed_batch(texts)

    for i, receipt_id in enumerate(ids):
        upsert_receipt(collection, receipt_id, embeddings[i], texts[i], metadatas[i])

    print(f"✓ Indexed {len(ids)} receipts into ChromaDB")

if __name__ == "__main__":
    main()
