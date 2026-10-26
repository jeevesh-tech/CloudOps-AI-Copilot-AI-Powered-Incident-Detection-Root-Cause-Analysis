---
incident_type: RDS_CONNECTION_EXHAUSTION
title: RDS Connection Exhaustion Runbook
tags: [rds, database, connections, pooling]
---

# RDS Connection Exhaustion

## Symptoms
- RDSConnections metric approaching or at max_connections
- Application errors: "too many connections" / connection timeout acquiring from pool
- Increased request failures for database-backed endpoints

## Likely Causes
- Connection pool misconfiguration (pool size too large relative to DB limit, or leaking connections)
- A spike in concurrent request volume
- Long-running queries holding connections open
- Multiple application instances scaled out without adjusting per-instance pool size

## Investigation Steps
1. Check current vs. max RDS connections and recent connection count trend.
2. Check application connection pool configuration (pool size, timeout, idle behavior).
3. Look for long-running or blocked queries in the database.
4. Correlate connection growth with recent scaling events or deployments.

## Recommended Actions
- Reduce per-instance connection pool size or introduce a connection pooler (e.g. RDS Proxy).
- Kill long-running/blocked queries if identified.
- Scale the RDS instance class or increase max_connections if structurally undersized.
- Add circuit breaking / backoff in the application for connection acquisition failures.
