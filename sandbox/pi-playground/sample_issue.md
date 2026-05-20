# Sample Finding: Retry-After Ignored

## Source
GitHub issue: firebase/genkit #5270

## Finding
The retry middleware includes RESOURCE_EXHAUSTED in default retry
statuses but uses pure exponential backoff without consulting the
provider's Retry-After header.

When a provider returns HTTP 429 with Retry-After: 60, the retry
middleware fires at 1000ms intervals inside the cooldown window.
All retries fail until the window expires naturally.

## Evidence
- DEFAULT_RETRY_STATUSES includes RESOURCE_EXHAUSTED
- No Retry-After header consulted in retry delay computation
- Anthropic returns retry-after: 60 on 429 responses
- OpenAI and Gemini also send Retry-After

## Classification
WAIT — Retry-After present, client ignores it
