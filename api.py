"""
Pitstop /classify — corpus-backed execution failure classifier.

POST /classify        — returns WAIT/CAP/STOP with corpus-grounded precedent.
GET  /health          — health check.
GET  /corpus          — corpus status.
GET  /exhaust/summary — operational intelligence from logged calls.
POST /mcp             — HTTP MCP endpoint (Streamable HTTP transport)
GET  /mcp             — MCP server info
"""

import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.responses import JSONResponse
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
    finding: Optional[str] = None
    context: Optional[dict] = None


class CorpusMatch(BaseModel):
    receipt_id: str
    repo: str
    pattern: str
    score: float


class Classification(BaseModel):
    decision: str
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
# MCP response formatter
# ---------------------------------------------------------------------------

def format_mcp_result(response: ClassifyResponse) -> str:
    classification = response.classification
    decision = classification.decision
    confidence = classification.confidence
    reason = classification.reason_code
    retry_after_ms = classification.retry_after_ms
    fix_shape = response.fix_shape
    corpus_matches = response.corpus_matches
    corpus_grounded = response.corpus_grounded

    lines = [
        f"Classification: {decision} (confidence: {confidence:.0%})",
        f"Reason: {reason}",
        f"Fix: {fix_shape}",
    ]

    if retry_after_ms:
        lines.append(f"Retry after: {retry_after_ms}ms")

    if corpus_grounded and corpus_matches:
        lines.append(f"\nMatched precedent ({len(corpus_matches)} receipts):")
        for match in corpus_matches[:3]:
            lines.append(
                f"  → {match.receipt_id}\n"
                f"    {match.pattern[:120]}\n"
                f"    Score: {match.score:.3f}"
            )

    lines.append(
        f"\nGrounded: {'Yes — corpus-backed' if corpus_grounded else 'No — rule-based only'}"
    )

    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# HTTP MCP endpoint — Streamable HTTP transport for Smithery
# Calls classification logic directly — no httpx round-trip, no timeout risk
# ---------------------------------------------------------------------------

@app.post("/mcp")
async def mcp_endpoint(request: FastAPIRequest):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}
        )

    method = body.get("method")
    request_id = body.get("id")

    if method == "initialize":
        return JSONResponse(content={
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pitstop", "version": "0.2.0"},
            }
        })

    if method == "tools/list":
        from mcp.server import TOOL_DEFINITION
        return JSONResponse(content={
            "jsonrpc": "2.0", "id": request_id,
            "result": {"tools": [TOOL_DEFINITION]}
        })

    if method == "tools/call":
        params = body.get("params", {})
        arguments = params.get("arguments", {})

        finding = arguments.get("finding", "")
        status = arguments.get("status", 429)
        retry_after = arguments.get("retry_after")
        provider = arguments.get("provider")

        headers = {}
        if retry_after:
            headers["retry-after"] = retry_after

        req = ClassifyRequest(
            status=status,
            headers=headers,
            finding=finding,
            provider=provider,
        )

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
        formatted = format_mcp_result(response)

        return JSONResponse(content={
            "jsonrpc": "2.0", "id": request_id,
            "result": {"content": [{"type": "text", "text": formatted}], "isError": False}
        })

    if method == "notifications/initialized":
        return JSONResponse(status_code=204, content={})

    return JSONResponse(content={
        "jsonrpc": "2.0", "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    })


@app.get("/mcp")
async def mcp_info():
    return {
        "name": "pitstop",
        "version": "0.2.0",
        "description": "Classify AI/API execution failures. Returns WAIT, CAP, or STOP with corpus-grounded precedent from 63 confirmed production failures.",
        "tools": ["pitstop_classify"],
    }

@app.get("/.well-known/mcp/server-card.json")
async def server_card():
    """
    Static server card for Smithery scanning.
    Bypasses automatic MCP initialization scan.
    """
    return {
        "name": "pitstop",
        "version": "0.2.0",
        "description": "Classify AI/API execution failures. Returns WAIT, CAP, or STOP with corpus-grounded precedent from 63 confirmed production failures. Call this when your agent hits a 429, quota error, or rate limit boundary.",
        "tools": [
            {
                "name": "pitstop_classify",
                "description": "Classify an AI/API execution failure. Returns WAIT, CAP, or STOP with fix shape and matched precedent from confirmed production failures.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "finding": {"type": "string"},
                        "status": {"type": "integer"},
                        "retry_after": {"type": "string"},
                        "provider": {"type": "string"}
                    },
                    "required": ["finding"]
                }
            }
        ],
        "homepage": "https://pitstop.dev",
        "repository": "https://github.com/pitstop-hq/pitstop"
    }
