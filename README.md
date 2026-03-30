# Pitstop

> Not all 429s are the same. Treat them the same and you burn budget.

Pitstop classifies execution failures before retry, failover, or enforcement logic makes the wrong decision.

This repo is the top-level home for Pitstop as a product and operating system.

It is not the evidence corpus itself, and it is not the discovery engine. It is the place where the following get defined clearly:

- what Pitstop is
- what Pitstop does
- how Pitstop should be used
- where free help ends and deeper work begins
- what the core primitives are

## Current wedge

Most systems treat rate limit failures too bluntly.

A 429 can mean very different things:

- **WAIT** — transient pressure; retry after delay
- **CAP** — concurrency / throughput pressure; reduce workers before retry
- **STOP** — quota or terminal exhaustion; do not retry, surface to caller

When those get collapsed into one response path, systems amplify pressure instead of absorbing it.

Pitstop exists to classify those failures before retry, failover, or enforcement logic makes the wrong decision.

## What lives here

This repository contains the operating docs for Pitstop:

- `PITSTOP_OPERATING_PRINCIPLES.md`
- `PITSTOP_VALUE_BOUNDARY.md`
- `PITSTOP_PRIMITIVES.md`

## What lives elsewhere

### `pitstop-truth`
Machine-readable corpus of execution failure receipts, taxonomy evidence, and canonical cases.

### `pitstop-radar`
Discovery engine for finding active, high-signal pain surfaces in the wild.

### `pitstop-check`
Static checker for surfacing retry / rate-limit handling mistakes in codebases.

### `pitstop-scan`
Diagnosis / surface experiments and landing-page-facing wedge work.

## Current state

Pitstop is still early.

What exists now:

- a live `/classify` primitive
- a growing corpus of real failure receipts
- repeated cross-system evidence of the same failure class
- early external adoption of the WAIT / CAP / STOP taxonomy in production code

What remains open:

- stronger workflow insertion
- clearer value capture
- making classification more inevitable in real execution paths

## The working question

The test: does classification happen before the wrong decision does?

That is the core Pitstop question.