"""
chroma.py — ChromaDB client wrapper for Pitstop.

Manages the ChromaDB collection and provides
clean query/upsert interfaces.
"""

import os
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

COLLECTION_NAME = "pitstop_receipts_v1"
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "chroma"


def get_client(db_path: Optional[Path] = None) -> chromadb.ClientAPI:
    path = db_path or DEFAULT_DB_PATH
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(path),
        settings=Settings(anonymized_telemetry=False),
    )


def get_collection(client: Optional[chromadb.ClientAPI] = None):
    c = client or get_client()
    return c.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_receipt(
    collection,
    receipt_id: str,
    embedding: list[float],
    document: str,
    metadata: dict,
) -> None:
    """
    Upsert a single receipt into ChromaDB.
    Safe to call multiple times — idempotent.
    """
    collection.upsert(
        ids=[receipt_id],
        embeddings=[embedding],
        documents=[document],
        metadatas=[metadata],
    )


def query_receipts(
    collection,
    query_embedding: list[float],
    n_results: int = 5,
) -> list[dict]:
    """
    Query ChromaDB for receipts similar to the query embedding.
    Returns a list of dicts with id, document, metadata, distance.
    """
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for i, receipt_id in enumerate(ids):
        output.append({
            "id": receipt_id,
            "document": docs[i],
            "metadata": metas[i],
            "distance": distances[i],
            "score": round(1 - distances[i], 4),
        })

    return output


def collection_count(collection=None) -> int:
    c = collection or get_collection()
    return c.count()
