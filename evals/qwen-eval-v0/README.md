# Pitstop Local Classifier Eval

# qwen-eval-v0

# Created: 2026-05-19

-----

## The Question

Can a local model (Qwen 7B via Ollama) classify AI/API execution failures as WAIT/CAP/STOP with enough accuracy, confidence, and speed to replace or supplement the Railway /classify endpoint?

This is not a research question.
This is a product question.

-----

## What This Eval Is

A semantic viability test.

We are testing whether a small local model can make the correct three-way classification decision (WAIT/CAP/STOP) given:

- HTTP status code
- Response headers
- Free-text finding description

We are NOT testing:

- Production operational viability
- Generalization to unseen cases
- Topology or propagation reasoning
- Retrieval-augmented classification
- Adversarial or ambiguous inputs
- Latency under production load

Those are separate evals. This is eval v0.

-----

## Ontology Clarification (Important)

The eval must respect the full Pitstop taxonomy.

WAIT/CAP/STOP is determined by:
status + headers + body together
NOT status code alone
NOT Retry-After duration alone

Specifically:

```
Retry-After is a floor, not a ceiling.
Long Retry-After does not imply STOP.
```

Correct case mapping:

WAIT:
429 + Retry-After present     → WAIT
Regardless of duration
UNLESS body confirms quota exhaustion

CAP:
429 + no Retry-After          → CAP (default)
429 + concurrency signals     → CAP
No header + no body signal    → CAP

STOP:
429 + body confirms quota/billing exhaustion → STOP
Non-429 status code                         → STOP
Very long Retry-After + quota body signal   → STOP

The eval cases must distinguish:
long transient throttle (WAIT)
vs confirmed quota exhaustion (STOP)

-----

## What We Are Building

A minimal eval harness:

```
pitstop-hq/evals/qwen-eval-v0/
  cases/          ground truth cases from corpus
  results/        output per run
  run_eval.py     the harness
  README.md       this file
```

-----

## The Eval Dataset

15 cases derived from pitstop-truth corpus receipts.
Cases are labeled and categorized by difficulty.

Easy cases (5): clear header presence/absence
Hard cases (10): ambiguous signals, body-only classification, topology patterns

Important caveat:
Cases are derived from the same corpus that informed the prompt design. This is a known limitation. The eval measures whether the model can apply the ontology correctly — not whether it generalizes to unseen cases. A blind eval with unseen cases is the next step.

-----

## The Prompt

The classification prompt uses an explicit
decision tree structure:

```
Has Retry-After header?
  YES → WAIT (regardless of duration)
    UNLESS body confirms quota exhaustion → STOP
  NO → check body
    Body confirms quota/billing exhaustion? → STOP
    No body signal → CAP (this is the default)
Non-429 status? → STOP
```

Key design decisions:

- CAP is the explicit default when no signal
- Long Retry-After duration alone = WAIT not STOP
- Body content required to classify as STOP
- One-word output + confidence score
- Temperature 0.1 for determinism

-----

## Results (Run v0.3 — 2026-05-19)

```
Model:    qwen2.5:7b via Ollama
Cases:    15
Correct:  15/15 (100%)
Latency:  ~29s avg per case (MacBook CPU)
```

By class:

```
WAIT:  4/4  (100%)  avg_confidence=0.95
CAP:   5/5  (100%)  avg_confidence=0.94
STOP:  6/6  (100%)  avg_confidence=0.96
```

By difficulty:

```
Easy:  5/5  (100%)
Hard:  10/10 (100%)
```

Routing simulation (confidence threshold=0.80):

```
Routed to local:      15/15 (100%)
Accuracy above threshold: 100%
Estimated cost savings: 100%
```

-----

## What This Proves

**Confirmed:**

```
Qwen 7B can correctly classify WAIT/CAP/STOP on bounded, curated, corpus-derived cases when given an explicit ontology-grounded prompt.
```

More specifically — this may prove:

```
Ontology clarity
+ tight interface
+ bounded task
+ explicit decision tree
> raw model capability
```

The prompt engineering did significant work here.
The model applied rules correctly.
Whether it reasons about the underlying patterns is not yet established.

**Not confirmed:**

```
Generalization to unseen cases
  — cases share ontological framing with prompt

Adversarial robustness
  — no malformed headers, contradictory signals,
    or intentionally ambiguous cases tested

Production latency viability
  — 29s avg is acceptable for batch
    not for real-time agent calls

Confidence calibration
  — high confidence scores not yet validated
    against a larger diverse dataset

Topology reasoning
  — finding text may have implied the answer
    without requiring true topology understanding

Railway replacement
  — Railway provides deployment, availability,
    corpus retrieval, MCP integration, and API surface
    This eval only tests the classification step

UNKNOWN handling
  — model forced to classify every case
    Real systems need an UNKNOWN output
    for ambiguous or low-evidence cases
```

-----

## Known Limitations

**1. Non-blind evaluation**
Cases derived from corpus that informed prompt design.
The model may be matching prompt-template structure rather than reasoning from first principles.

**2. Small sample size**
15 cases is insufficient to establish generalization.
Minimum 50-100 cases needed for credible claims.

**3. Latency on MacBook CPU**
~29s per case on MacBook CPU inference.
Operationally viable on Mac Mini M2 (~5-8s).
Not viable for real-time agent calls on current hardware.

**4. Confidence score validity**
High confidence scores (0.95) not yet validated.
May reflect model overconfidence not calibration.

**5. No retrieval integration**
This eval tests classification in isolation.
The full Pitstop architecture adds corpus retrieval.
Whether retrieval improves accuracy is unknown.

**6. No UNKNOWN class**
All cases have a clear ground truth label.
Real production cases may be genuinely ambiguous.
Model currently forced to overclassify.

-----

## What Comes Next

**Eval v1 — Generalization test:**
50+ cases
Unseen receipts not used in prompt design Shuffled wording Adversarial and ambiguous inputs Malformed headers Contradictory evidence

**Eval v2 — Retrieval integration:**
Qwen + ChromaDB together
Does retrieval improve accuracy on hard cases?
How does latency change?

**Eval v3 — Production simulation:**
Concurrent classification calls
Warm vs cold model latency
Memory pressure under load
Model availability and restart behavior

**Eval v4 — Calibration:**
Is confidence score predictive of correctness?
What threshold minimizes false-confidence routing?

-----

## Honest Conclusion

```
Qwen 7B appears semantically viable for bounded WAIT/CAP/STOP classification under constrained prompts and curated cases.

The most important finding may be:
ontology clarity and task bounding matter more than model size.

Further evaluation required before production routing decisions are made.
```

This is a strong first signal.
It is not a production decision.

-----

## The Broader Insight

Consistent with findings from Pi/Qwen ecosystem:

```
Small focused agents with narrow context and explicit ontologies outperform large general agents with broad scope.

The classification is the interface.
The ontology and corpus remain the moat.
```

-----

## Run It

```bash
# Prerequisites
brew install ollama
ollama pull qwen2.5:7b

# Run eval
cd ~/Development-Projects/pitstop-hq
python3 evals/qwen-eval-v0/run_eval.py --verbose
```

-----

## Relationship To Pitstop

This eval directly addresses CONTEXT.md §17:

“Can local models classify reliably enough?”

Preliminary answer: YES for semantic viability.
Full answer: requires eval v1 (generalization test).

Update CONTEXT.md §17 after eval v1 completes.