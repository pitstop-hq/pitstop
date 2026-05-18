"""
Pitstop MCP Server

Exposes Pitstop's /classify endpoint as an MCP tool
that any Claude-compatible agent can call when
execution fails at an API boundary.

Tool: pitstop_classify
  Input:  finding (string) — description of the failure
          status (int, optional) — HTTP status code
          retry_after (string, optional) — Retry-After header value
          provider (string, optional) — provider name
  Output: WAIT/CAP/STOP + fix shape + corpus precedent
"""

import sys
import json
import httpx
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Local development: point to local uvicorn
# Production: point to Railway deployment
PITSTOP_BASE_URL = "http://localhost:8000"

# Override with environment variable in production
import os
PITSTOP_BASE_URL = os.environ.get("PITSTOP_URL", PITSTOP_BASE_URL)


# ---------------------------------------------------------------------------
# MCP Tool Definition
# ---------------------------------------------------------------------------

TOOL_DEFINITION = {
    "name": "pitstop_classify",
    "description": (
        "Classify an AI/API execution failure. "
        "Call this when your agent hits a 429, quota error, "
        "rate limit, or any execution boundary failure. "
        "Returns WAIT, CAP, or STOP with a fix shape and "
        "matched precedent from confirmed production failures."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "finding": {
                "type": "string",
                "description": (
                    "Description of the failure. Examples: "
                    "'429 without Retry-After header', "
                    "'quota exhausted after 1000 requests', "
                    "'retry storm amplifying provider errors'"
                ),
            },
            "status": {
                "type": "integer",
                "description": "HTTP status code if available (e.g. 429, 402, 503)",
            },
            "retry_after": {
                "type": "string",
                "description": "Value of Retry-After header if present",
            },
            "provider": {
                "type": "string",
                "description": "Provider name if known (e.g. anthropic, openai, gemini)",
            },
        },
        "required": ["finding"],
    },
}


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def call_classify(
    finding: str,
    status: int = 429,
    retry_after: str = None,
    provider: str = None,
) -> dict:
    """
    Call the Pitstop /classify endpoint and return structured result.
    """
    headers = {}
    if retry_after:
        headers["retry-after"] = retry_after

    payload = {
        "status": status,
        "headers": headers,
        "finding": finding,
    }
    if provider:
        payload["provider"] = provider

    try:
        response = httpx.post(
            f"{PITSTOP_BASE_URL}/classify",
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException:
        return {"error": "Pitstop classify timed out", "fallback": "WAIT"}
    except Exception as e:
        return {"error": str(e), "fallback": "WAIT"}


def format_result(result: dict) -> str:
    """
    Format the classify result as a clean string for the agent.
    """
    if "error" in result:
        return (
            f"Pitstop classification unavailable: {result['error']}\n"
            f"Suggested fallback: {result.get('fallback', 'WAIT')}"
        )

    classification = result.get("classification", {})
    decision = classification.get("decision", "UNKNOWN")
    confidence = classification.get("confidence", 0)
    reason = classification.get("reason_code", "")
    retry_after_ms = classification.get("retry_after_ms")
    fix_shape = result.get("fix_shape", "")
    corpus_matches = result.get("corpus_matches", [])
    corpus_grounded = result.get("corpus_grounded", False)

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
                f"  → {match['receipt_id']}\n"
                f"    {match['pattern'][:120]}\n"
                f"    Score: {match['score']:.3f}"
            )

    lines.append(
        f"\nGrounded: {'Yes — corpus-backed' if corpus_grounded else 'No — rule-based only'}"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP stdio server
# ---------------------------------------------------------------------------

def handle_request(request: dict) -> dict:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "pitstop",
                    "version": "0.2.0",
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [TOOL_DEFINITION]},
        }

    if method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name != "pitstop_classify":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                },
            }

        finding = arguments.get("finding", "")
        status = arguments.get("status", 429)
        retry_after = arguments.get("retry_after")
        provider = arguments.get("provider")

        result = call_classify(
            finding=finding,
            status=status,
            retry_after=retry_after,
            provider=provider,
        )

        formatted = format_result(result)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": formatted,
                    }
                ],
                "isError": "error" in result,
            },
        }

    if method == "notifications/initialized":
        return None

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
        },
    }


def main():
    """
    Run MCP server over stdio.
    Reads JSON-RPC requests from stdin, writes responses to stdout.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)

        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
