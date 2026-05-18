"""
pitstop_embed.py — single embedding abstraction for all Pitstop.

Swap the implementation here without touching anything else.
Current: fastembed (free, local, Python 3.13 compatible)
Future:  sentence-transformers (when torch supports 3.13),
         or fine-tuned domain model — swap here only.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def _get_model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


def pitstop_embed(text: str) -> list[float]:
    """
    Embed a text string into a vector.
    Returns a list of floats suitable for ChromaDB.
    """
    model = _get_model()
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def pitstop_embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts. More efficient than calling pitstop_embed repeatedly.
    """
    model = _get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]
