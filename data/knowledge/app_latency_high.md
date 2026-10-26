---
incident_type: APP_LATENCY_HIGH
title: Application Latency High Runbook
tags: [latency, performance, downstream, timeout]
---

# Application Latency High

## Symptoms
- AppLatency metric well above baseline (P99/P50 elevated)
- Increased request timeouts
- Possible correlation with CPU pressure or downstream slowness

## Likely Causes
- Downstream dependency (database, external API) responding slowly
- Resource contention (CPU, memory, connections) on the service itself
- Inefficient code path introduced recently (N+1 queries, missing cache, etc.)
- Increased load beyond current capacity

## Investigation Steps
1. Break down latency by segment: application processing time vs. downstream call time.
2. Check CPU/RDS connection metrics for concurrent resource pressure.
3. Check whether a recent deployment introduced a slow code path.
4. Check downstream dependency latency/error rates.

## Recommended Actions
- Scale out the service if the bottleneck is capacity-related.
- Add or fix caching for expensive/repeated operations.
- Optimize or roll back the offending code path if deployment-related.
- Add timeouts and circuit breakers around slow downstream dependencies.
