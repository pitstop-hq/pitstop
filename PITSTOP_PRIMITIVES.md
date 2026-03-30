# Pitstop Primitives

Pitstop exists to classify execution failures before retry, failover, or enforcement logic makes the wrong decision.

These are the three core primitives.

---

## 1. Classify

**Question:**  
What does this failure actually mean?

**When to use it:**  
Use this when a request fails and the system needs to decide what to do next.

Typical examples:
- HTTP 429 responses
- ambiguous rate limit errors
- failures where the wrong retry behavior could amplify cost or pressure

**Input:**  
- status code
- response headers
- optional provider / context

**Output:**  
- failure class
- recommended next action
- first knob to adjust

For the current 429 wedge, the output is:

- **WAIT** — transient pressure; retry after delay
- **CAP** — concurrency / throughput pressure; reduce workers before retry
- **STOP** — quota or terminal exhaustion; do not retry; surface to caller

**Example:**  

Input:
- `status = 429`
- `retry-after = 30`

Output:
- `WAIT`
- honor `Retry-After`
- first knob: retry delay floor

**Why it matters:**  
Most systems treat all 429s the same. That is the mistake.  
Pitstop starts by classifying the failure before the system acts on it.

---

## 2. Diagnose

**Question:**  
What is wrong in this retry / failover / polling setup?

**When to use it:**  
Use this when a system is already showing symptoms such as:
- repeated 429s
- retry loops
- quota burn
- timeouts that cascade
- polling patterns that amplify pressure
- error messages that do not match the actual failure mode

**Input:**  
- redacted failure block
- retry config
- relevant logs
- optional headers / timestamps / request cadence

**Output:**  
- likely failure class
- likely misclassification or control failure
- first knob to adjust
- bounded next step

Typical examples:
- Retry-After ignored at the call site
- all 429s treated as retryable
- timeout handled as rate limit
- multi-instance polling amplifying burst pressure
- hidden rolling-window or policy-gated limiter surfaced as generic “rate limit”

**Why it matters:**  
Classification tells you what a failure means.  
Diagnosis tells you why the current system is still behaving incorrectly.

---

## 3. Guard

**Question:**  
What should the system do before it continues?

**When to use it:**  
Use this at the point where a runtime would otherwise:
- retry
- rotate credentials
- fail over providers
- continue polling
- keep spending budget blindly

**Input:**  
- classified failure
- optional runtime context (workers, retries, budget, provider, policy)

**Output:**  
- delay
- shrink
- fail fast
- or surface immediately

For the current wedge, the guard behavior is conceptually:

- **WAIT** → delay, then retry
- **CAP** → reduce concurrency, then retry carefully
- **STOP** → do not retry; surface to caller

**Why it matters:**  
This is the bridge from understanding to enforcement.

Without a guard, systems can classify correctly and still behave badly.  
With a guard, the wrong retry decision becomes harder to make.

---

## How the primitives relate

The primitives are sequential:

1. **Classify** the failure
2. **Diagnose** why the current system is handling it badly
3. **Guard** the next action so the failure is not amplified

In other words:

`failure → classify → diagnose → guard`

That is the core Pitstop motion.

---

## Current state

Today, Pitstop is strongest at:

- classifying ambiguous 429 failures
- diagnosing real retry / rate-limit handling mistakes
- grounding that diagnosis in a growing corpus of execution failure receipts

The longer-term direction is to make these primitives easier to call from real workflows, and eventually harder to bypass in production execution paths.

---

## Working wedge

The current public wedge is narrow on purpose:

> Pitstop helps agent builders turn ambiguous 429s into the right action: wait, shrink, or stop.

That is the starting point, not the full boundary of the problem.

---

## See also

- `README.md`
- [`pitstop-truth`](https://github.com/SirBrenton/pitstop-truth)
- [`pitstop-check`](https://github.com/SirBrenton/pitstop-check)