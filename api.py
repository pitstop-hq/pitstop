"""
Pitstop /classify — corpus-backed execution failure classifier.

POST /classify        — returns WAIT/CAP/STOP with corpus-grounded precedent.
GET  /health          — health check.
GET  /corpus          — corpus status.
GET  /exhaust/summary — operational intelligence from logged calls.
"""

import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

# Add parent to path for retrieval imports
sys.path.insert(0, str(Path(__file__).parent))

# ---------------------------------------------------------------------------
# Exhaust log path
# ---------------------------------------------------------------------------

EXHAUST_PATH = Path("data/exhaust.jsonl")


# ---------------------------------------------------------------------------
# Startup — build ChromaDB index
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    try:
        from scripts.build_index import main as build_index
        build_index()
    except Exception as e:
        print(f"Warning: index build failed: {e}")
    yield


app = FastAPI(
    title="Pitstop",
    description="The reliability layer for AI agents.",
    version="0.2.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Lazy ChromaDB init — only loads when first request arrives
# ---------------------------------------------------------------------------

_collection = None


def get_collection():
    global _collection
    if _collection is None:
        try:
            from retrieval.chroma import get_collection as _get_col
            _collection = _get_col()
        except Exception as e:
            print(f"Warning: ChromaDB unavailable: {e}")
            _collection = None
    return _collection


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ClassifyRequest(BaseModel):
    status: int
    headers: dict = {}
    provider: Optional[str] = None
    finding: Optional[str] = None  # free-text finding for corpus search
    context: Optional[dict] = None


class CorpusMatch(BaseModel):
    receipt_id: str
    repo: str
    pattern: str
    score: float


class Classification(BaseModel):
    decision: str          # WAIT | CAP | STOP
    confidence: float
    reason_code: str
    retry_after_ms: Optional[int] = None
    scope: str


class ClassifyResponse(BaseModel):
    classification: Classification
    fix_shape: str
    corpus_matches: list[CorpusMatch] = []
    corpus_grounded: bool = False


# ---------------------------------------------------------------------------
# Exhaust logging — zero friction, caller unaware
# ---------------------------------------------------------------------------

def log_exhaust(req: ClassifyRequest, response: ClassifyResponse) -> None:
    """
    Append every classify call to exhaust log.
    Never breaks classification on logging failure.
    """
    try:
        EXHAUST_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "finding": req.finding or "",
            "status": req.status,
            "provider": req.provider or "",
            "decision": response.classification.decision,
            "confidence": response.classification.confidence,
            "reason_code": response.classification.reason_code,
            "retry_after_ms": response.classification.retry_after_ms,
            "corpus_grounded": response.corpus_grounded,
            "top_match": response.corpus_matches[0].receipt_id
                         if response.corpus_matches else None,
            "top_score": response.corpus_matches[0].score
                         if response.corpus_matches else None,
            "match_count": len(response.corpus_matches),
        }
        with open(EXHAUST_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Retry-After parsing
# ---------------------------------------------------------------------------

def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    v = value.strip()
    try:
        secs = float(v)
        return secs if secs >= 0 else None
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        return delta if delta >= 0 else 0.0
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Corpus retrieval
# ---------------------------------------------------------------------------

def query_corpus(finding: str, n: int = 3) -> list[CorpusMatch]:
    """
    Query ChromaDB for receipts matching the finding.
    Returns empty list if ChromaDB unavailable.
    """
    try:
        from retrieval.embed import pitstop_embed
        from retrieval.chroma import query_receipts

        collection = get_collection()
        if collection is None:
            return []

        embedding = pitstop_embed(finding)
        results = query_receipts(collection, embedding, n_results=n)

        matches = []
        for r in results:
            meta = r.get("metadata", {})
            matches.append(CorpusMatch(
                receipt_id=meta.get("receipt_id", r["id"]),
                repo=meta.get("repo", "unknown"),
                pattern=meta.get("hazard_summary", "")[:200],
                score=r["score"],
            ))
        return matches

    except Exception as e:
        print(f"Corpus query failed: {e}")
        return []


def build_finding_text(req: ClassifyRequest) -> str:
    """
    Build finding text for corpus search from the request.
    Uses explicit finding field if provided, otherwise builds
    from status + headers.
    """
    if req.finding:
        return req.finding

    parts = [f"HTTP {req.status}"]

    ra = (
        req.headers.get("retry-after")
        or req.headers.get("Retry-After")
        or req.headers.get("x-ratelimit-reset-after")
    )
    if ra:
        parts.append(f"Retry-After: {ra}")

    if req.provider:
        parts.append(f"provider: {req.provider}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------

def classify_request(req: ClassifyRequest) -> tuple[str, float, str, Optional[int], str, str]:
    """
    Returns: (decision, confidence, reason_code, retry_after_ms, scope, fix_shape)
    """
    ra_raw = (
        req.headers.get("retry-after")
        or req.headers.get("Retry-After")
        or req.headers.get("x-ratelimit-reset-after")
        or None
    )
    ra_s = parse_retry_after(ra_raw)
    retry_after_ms = int(ra_s * 1000) if ra_s is not None else None
    scope = "provider" if req.provider else "request"

    if req.status != 429:
        return (
            "STOP", 0.95, "non_429_status",
            None, scope,
            "Do not retry. Surface the error to the caller for explicit handling.",
        )

    if ra_s is not None and ra_s > 60:
        return (
            "STOP", 0.91, "quota_exhaustion_retry_after_exceeds_60s",
            retry_after_ms, scope,
            "Do not retry. Wait for quota reset. Surface to caller with retry_after_ms.",
        )

    if ra_s is not None and ra_s <= 60:
        return (
            "WAIT", 0.92, "retry_after_present",
            retry_after_ms, scope,
            "Honor Retry-After as the minimum retry delay before local backoff.",
        )

    return (
        "CAP", 0.74, "no_retry_after_likely_concurrency_cap",
        None, scope,
        "Reduce concurrent workers. Do not retry immediately. "
        "Add jitter before next attempt.",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest):
    decision, confidence, reason_code, retry_after_ms, scope, fix_shape = classify_request(req)

    finding_text = build_finding_text(req)
    corpus_matches = query_corpus(finding_text, n=3)

    response = ClassifyResponse(
        classification=Classification(
            decision=decision,
            confidence=confidence,
            reason_code=reason_code,
            retry_after_ms=retry_after_ms,
            scope=scope,
        ),
        fix_shape=fix_shape,
        corpus_matches=corpus_matches,
        corpus_grounded=len(corpus_matches) > 0,
    )

    log_exhaust(req, response)
    return response


@app.get("/health")
def health():
    collection = get_collection()
    corpus_count = 0
    if collection is not None:
        try:
            from retrieval.chroma import collection_count
            corpus_count = collection_count(collection)
        except Exception:
            pass

    return {
        "status": "ok",
        "version": "0.2.0",
        "corpus_indexed": corpus_count,
        "corpus_grounded": corpus_count > 0,
    }


@app.get("/corpus")
def corpus_status():
    collection = get_collection()
    if collection is None:
        return {"status": "unavailable", "count": 0}

    try:
        from retrieval.chroma import collection_count
        count = collection_count(collection)
        return {
            "status": "ok",
            "count": count,
            "collection": "pitstop_receipts_v1",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/exhaust/summary")
def exhaust_summary():
    """
    Summary of exhaust log — operational intelligence.
    """
    if not EXHAUST_PATH.exists():
        return {"total_calls": 0, "decisions": {}, "providers": {}}

    records = []
    with open(EXHAUST_PATH) as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    if not records:
        return {"total_calls": 0}

    decisions = {}
    providers = {}
    ungrounded = 0
    novel_patterns = []

    for r in records:
        d = r.get("decision", "unknown")
        decisions[d] = decisions.get(d, 0) + 1

        p = r.get("provider", "unknown") or "unknown"
        providers[p] = providers.get(p, 0) + 1

        if not r.get("corpus_grounded"):
            ungrounded += 1
            if r.get("finding"):
                novel_patterns.append(r["finding"][:100])

    return {
        "total_calls": len(records),
        "decisions": decisions,
        "providers": providers,
        "corpus_grounded_rate": round(
            (len(records) - ungrounded) / len(records), 3
        ) if records else 0,
        "ungrounded_calls": ungrounded,
        "potential_novel_patterns": novel_patterns[:5],
    }
