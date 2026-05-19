#!/usr/bin/env python3
"""
run_eval.py — Pitstop local classifier eval harness.

Tests Qwen (via Ollama) against ground truth cases
from the pitstop-truth corpus.

Usage:
    python3 run_eval.py
    python3 run_eval.py --model qwen2.5:7b
    python3 run_eval.py --cases evals/qwen-eval-v0/cases/cases.json
    python3 run_eval.py --verbose
"""

import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


OLLAMA_URL = "http://localhost:11434/api/generate"

CLASSIFY_PROMPT = """You are a production failure classifier.

Given an AI/API execution failure, classify it as:

WAIT  — Retry-After header is present in the response
        Honor the header delay and retry after
        Long Retry-After alone does NOT mean STOP
        Even Retry-After: 600 or Retry-After: 3600 is WAIT
        UNLESS the body explicitly confirms quota exhaustion

CAP   — No Retry-After header AND no body signal
        This is the DEFAULT when no header is present
        Concurrency or throughput limit
        Reduce concurrent workers, add jitter
        Hidden retries, unbounded loops, stacked amplification
        Headerless 429 with no quota message = CAP

STOP  — Quota exhaustion CONFIRMED by response body
        Body says: "quota exhausted", "credit limit",
        "billing required", "extra usage required"
        OR non-429 status code (408, 402, 503, etc.)
        OR Retry-After present AND body confirms quota window

Decision rules:
  Has Retry-After header?
    YES → WAIT (regardless of duration)
      UNLESS body confirms quota exhaustion → STOP
    NO → check body
      Body confirms quota/billing exhaustion? → STOP
      No body signal → CAP (this is the default)
  Non-429 status? → STOP

Respond with exactly one word on the first line: WAIT, CAP, or STOP
Then on the next line your confidence as a decimal between 0 and 1.

Example response:
CAP
0.88

Failure:
Status: {status}
Headers: {headers}
Finding: {finding}"""


def call_ollama(model: str, prompt: str) -> tuple[str, float, float]:
    """
    Call Ollama API. Returns (response_text, latency_ms, tokens_estimated).
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 20,
        }
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            latency_ms = (time.time() - start) * 1000
            response_text = result.get("response", "").strip()
            tokens = result.get("eval_count", 0) + result.get("prompt_eval_count", 0)
            return response_text, latency_ms, float(tokens)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama not reachable: {e}. Is ollama running?")


def parse_response(text: str) -> tuple[str, float]:
    """
    Parse model output into (decision, confidence).
    Expected format:
        WAIT
        0.92
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    decision = "UNKNOWN"
    confidence = 0.5

    if lines:
        word = lines[0].upper().strip(".,;:")
        if word in ("WAIT", "CAP", "STOP"):
            decision = word

    if len(lines) >= 2:
        try:
            confidence = float(lines[1])
            confidence = max(0.0, min(1.0, confidence))
        except ValueError:
            confidence = 0.5

    return decision, confidence


def run_eval(model: str, cases_path: Path, verbose: bool = False) -> dict:
    cases = json.loads(cases_path.read_text())

    print(f"\nPitstop Local Classifier Eval")
    print(f"Model: {model}")
    print(f"Cases: {len(cases)}")
    print(f"{'='*50}\n")

    results = []
    correct = 0
    total_latency = 0
    total_tokens = 0

    by_class = {}
    by_difficulty = {"easy": {"correct": 0, "total": 0}, "hard": {"correct": 0, "total": 0}}
    failures = []

    for i, case in enumerate(cases):
        case_id = case["id"]
        expected = case["expected"]
        difficulty = case["difficulty"]
        headers_str = json.dumps(case["headers"]) if case["headers"] else "none"

        prompt = CLASSIFY_PROMPT.format(
            status=case["status"],
            headers=headers_str,
            finding=case["finding"],
        )

        print(f"[{i+1:02d}/{len(cases)}] {case_id} ({difficulty}) expected={expected}...", end=" ")

        try:
            raw_response, latency_ms, tokens = call_ollama(model, prompt)
            decision, confidence = parse_response(raw_response)
        except Exception as e:
            print(f"ERROR: {e}")
            decision = "ERROR"
            confidence = 0.0
            latency_ms = 0.0
            tokens = 0.0

        is_correct = decision == expected
        if is_correct:
            correct += 1

        total_latency += latency_ms
        total_tokens += tokens

        # Track by class
        if expected not in by_class:
            by_class[expected] = {"correct": 0, "total": 0, "confidences": []}
        by_class[expected]["total"] += 1
        by_class[expected]["confidences"].append(confidence)
        if is_correct:
            by_class[expected]["correct"] += 1

        # Track by difficulty
        by_difficulty[difficulty]["total"] += 1
        if is_correct:
            by_difficulty[difficulty]["correct"] += 1

        status_str = "✓" if is_correct else "✗"
        print(f"{status_str} got={decision} conf={confidence:.2f} latency={latency_ms:.0f}ms")

        if verbose and not is_correct:
            print(f"    Expected: {expected}")
            print(f"    Got:      {decision} (confidence {confidence:.2f})")
            print(f"    Finding:  {case['finding'][:100]}")
            print(f"    Reason:   {case.get('reasoning', '')}")
            print()

        result = {
            "case_id": case_id,
            "receipt_id": case["receipt_id"],
            "difficulty": difficulty,
            "expected": expected,
            "got": decision,
            "confidence": confidence,
            "correct": is_correct,
            "latency_ms": round(latency_ms),
            "tokens": int(tokens),
        }
        results.append(result)

        if not is_correct:
            failures.append({
                "case_id": case_id,
                "receipt_id": case["receipt_id"],
                "expected": expected,
                "got": decision,
                "confidence": confidence,
                "finding": case["finding"][:200],
                "latency_ms": round(latency_ms),
            })

    # Build summary
    total = len(cases)
    accuracy = correct / total if total > 0 else 0
    avg_latency = total_latency / total if total > 0 else 0
    avg_tokens = total_tokens / total if total > 0 else 0

    # Confidence routing simulation
    threshold = 0.80
    routed_local = [r for r in results if r["confidence"] >= threshold]
    routed_escalate = [r for r in results if r["confidence"] < threshold]
    local_accuracy = (
        sum(1 for r in routed_local if r["correct"]) / len(routed_local)
        if routed_local else 0
    )
    savings_pct = round(len(routed_local) / total * 100) if total > 0 else 0

    # Clean up by_class for output
    by_class_clean = {}
    for cls, data in by_class.items():
        confs = data["confidences"]
        by_class_clean[cls] = {
            "correct": data["correct"],
            "total": data["total"],
            "accuracy": round(data["correct"] / data["total"], 3) if data["total"] else 0,
            "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0,
        }

    by_difficulty_clean = {}
    for diff, data in by_difficulty.items():
        by_difficulty_clean[diff] = {
            "correct": data["correct"],
            "total": data["total"],
            "accuracy": round(data["correct"] / data["total"], 3) if data["total"] else 0,
        }

    # Determine recommendation
    if accuracy >= 0.80 and by_difficulty_clean.get("easy", {}).get("accuracy", 0) >= 0.90:
        recommendation = "viable"
    elif accuracy >= 0.70:
        recommendation = "needs_routing"
    else:
        recommendation = "not_viable"

    summary = {
        "model": model,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "total_cases": total,
        "correct": correct,
        "accuracy": round(accuracy, 3),
        "avg_latency_ms": round(avg_latency),
        "avg_tokens_per_case": round(avg_tokens),
        "by_class": by_class_clean,
        "by_difficulty": by_difficulty_clean,
        "confidence_routing_simulation": {
            "threshold": threshold,
            "routed_to_local": len(routed_local),
            "routed_to_escalation": len(routed_escalate),
            "local_accuracy_above_threshold": round(local_accuracy, 3),
            "estimated_cost_savings_pct": savings_pct,
        },
        "failures": failures,
        "recommendation": recommendation,
        "cases": results,
    }

    # Print summary
    print(f"\n{'='*50}")
    print(f"RESULTS")
    print(f"{'='*50}")
    print(f"Accuracy:       {correct}/{total} ({accuracy:.0%})")
    print(f"Avg latency:    {avg_latency:.0f}ms")
    print(f"Recommendation: {recommendation.upper()}")
    print()
    print(f"By class:")
    for cls, data in by_class_clean.items():
        print(f"  {cls}: {data['correct']}/{data['total']} ({data['accuracy']:.0%}) avg_conf={data['avg_confidence']:.2f}")
    print()
    print(f"By difficulty:")
    for diff, data in by_difficulty_clean.items():
        print(f"  {diff}: {data['correct']}/{data['total']} ({data['accuracy']:.0%})")
    print()
    print(f"Routing simulation (threshold={threshold}):")
    print(f"  Local:      {len(routed_local)} cases ({savings_pct}%) accuracy={local_accuracy:.0%}")
    print(f"  Escalate:   {len(routed_escalate)} cases")
    print()

    if failures:
        print(f"Failures ({len(failures)}):")
        for f in failures:
            print(f"  {f['case_id']}: expected={f['expected']} got={f['got']} conf={f['confidence']:.2f}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Pitstop local classifier eval")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model name")
    parser.add_argument(
        "--cases",
        default="evals/qwen-eval-v0/cases/cases.json",
        help="Path to cases JSON file"
    )
    parser.add_argument("--verbose", action="store_true", help="Show failure details")
    parser.add_argument("--output", default=None, help="Output JSON path (auto-generated if not set)")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        raise SystemExit(f"Cases file not found: {cases_path}")

    summary = run_eval(
        model=args.model,
        cases_path=cases_path,
        verbose=args.verbose,
    )

    # Save results
    if args.output:
        output_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_model = args.model.replace(":", "-").replace("/", "-")
        output_path = Path(f"evals/qwen-eval-v0/results/{safe_model}_{ts}.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2))
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
