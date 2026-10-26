---
incident_type: ALB_5XX_SPIKE
title: ALB 5xx Spike Runbook
tags: [alb, load-balancer, 5xx, health-check]
---

# ALB 5xx Spike

## Symptoms
- ALB5xx metric elevated above baseline
- Target group health checks failing for one or more targets
- Users experiencing intermittent request failures

## Likely Causes
- Unhealthy or crashing application targets
- Application-level errors (unhandled exceptions, timeouts) under load
- A bad deployment causing targets to fail health checks
- Downstream dependency failure causing cascading errors

## Investigation Steps
1. Check target group health status and count of unhealthy targets.
2. Check whether a deployment occurred shortly before the 5xx spike.
3. Review application error logs for exception patterns during the spike window.
4. Check downstream dependency health (database, external APIs).

## Recommended Actions
- Roll back the most recent deployment if it correlates with the spike.
- Restart/replace unhealthy targets.
- Add or tune health check grace periods if targets are flapping during warm-up.
- Investigate and fix the root application error causing 5xx responses.
