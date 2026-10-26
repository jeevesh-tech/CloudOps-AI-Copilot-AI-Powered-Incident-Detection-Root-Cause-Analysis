---
incident_type: APP_LATENCY_LOW
title: Application Latency Abnormally Low Runbook
tags: [latency, circuit-breaker, fail-fast, short-circuit]
---

# Application Latency Abnormally Low

## Symptoms
- AppLatency metric far below normal baseline
- Requests completing suspiciously fast, often with error responses
- Possible circuit breaker OPEN state or upstream failing fast

## Likely Causes
- A circuit breaker has opened and is fast-failing requests without doing real work
- An upstream dependency is returning immediate errors (e.g. auth failures, malformed requests)
- A caching layer is returning stale/empty responses without hitting the real backend
- A bug causing early-return responses that skip actual processing

## Investigation Steps
1. Check circuit breaker state and recent trip events for this service.
2. Sample recent responses to confirm whether they are valid or empty/error placeholders.
3. Check error rate alongside latency; abnormally low latency with high error rate strongly suggests fail-fast behavior.
4. Check for recent changes to caching or short-circuit logic.

## Recommended Actions
- Investigate and resolve the underlying failure causing the circuit breaker to trip.
- Verify cache correctness if a caching layer is suspected of returning empty/stale data.
- Add monitoring on response validity, not just latency and error rate, to catch this pattern earlier.
