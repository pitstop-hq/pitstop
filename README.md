# Pitstop

The reliability layer for AI agents.

When your agent fails at an execution boundary, Pitstop tells it what happened, what it costs, and how to recover.

-----

## The truck stop for AI agents

Agents pull in when execution fails.
They get what they need and get back on the road.
Every stop makes the next stop faster.

-----

## Install

[![smithery badge](https://smithery.ai/badge/brentondwilliams/pitstop)](https://smithery.ai/servers/brentondwilliams/pitstop)

[![Add to Kiro](https://kiro.dev/images/add-to-kiro.svg)](https://kiro.dev/launch/mcp/add?name=Pitstop&config=%7B%22url%22%3A%22https%3A%2F%2Fweb-production-273d3.up.railway.app%22%2C%22disabled%22%3Afalse%2C%22autoApprove%22%3A%5B%5D%7D)

-----

## /classify

POST a 429 status + headers, get back a classification:

```bash
curl -s -X POST https://web-production-273d3.up.railway.app/classify \
  -H "Content-Type: application/json" \
  -d '{"status":429,"headers":{"retry-after":"30"},"provider":"anthropic"}'
```

Returns: WAIT / CAP / STOP + fix shape + matched corpus precedent.

-----

## The corpus

63 production failure receipts.
14 confirmed and merged by maintainers.

github.com/SirBrenton/pitstop-truth

-----

## Architecture

```
pitstop-truth (corpus)
      ↓
ChromaDB (local vector index)
      ↓
/classify (Railway endpoint)
      ↓
MCP server (agents call this)
```

-----

## Contact

brent@pitstop.dev
pitstop.dev
@SirBrenton on GitHub