"""
Simulated application log collection for the Investigation Engine.

Phase 1 has no real application emitting logs, so this module synthesizes plausible
log lines correlated with the incident type. Future AWS mapping: this becomes a
CloudWatch Logs Insights query (or similar) against real application log groups.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_LOG_TEMPLATES = {
    "ECS_CPU_HIGH": [
        ("WARN", "Task {service} CPU utilization sustained above 90% for 5 minutes"),
        ("INFO", "Auto-scaling target tracking policy evaluating scale-out"),
        ("ERROR", "Request processing latency increasing under CPU pressure"),
    ],
    "RDS_CONNECTION_EXHAUSTION": [
        ("ERROR", "connection pool exhausted: unable to acquire connection within timeout"),
        ("WARN", "RDS connection count approaching max_connections limit"),
        ("ERROR", "Database query failed: too many connections"),
    ],
    "ALB_5XX_SPIKE": [
        ("ERROR", "Upstream target returned 502 Bad Gateway"),
        ("ERROR", "Target group health check failing for 2 of 4 targets"),
        ("WARN", "ALB request error rate exceeding baseline"),
    ],
    "DEPLOYMENT_REGRESSION": [
        ("INFO", "Deployment {service}:v-next rolled out to 100% of tasks"),
        ("ERROR", "Elevated error rate detected immediately after deployment"),
        ("WARN", "Response time regression correlated with latest deployment"),
    ],
    "APP_LATENCY_HIGH": [
        ("WARN", "P99 latency exceeding SLO threshold"),
        ("WARN", "Downstream dependency call taking longer than expected"),
        ("ERROR", "Request timeout while waiting on downstream service"),
    ],
    "APP_LATENCY_LOW": [
        ("WARN", "Request latency abnormally low; possible short-circuit or fail-fast path"),
        ("ERROR", "Circuit breaker OPEN: requests failing immediately"),
        ("WARN", "Response payloads smaller than expected; suspect early-exit responses"),
    ],
}

_DEFAULT_TEMPLATES = [
    ("INFO", "Service {service} operating within normal parameters"),
]


def collect_logs(incident: dict, count: int = 3) -> list[dict]:
    """Generate synthetic application log lines relevant to this incident's type."""
    incident_type = incident.get("incident_type")
    service = incident.get("service", "unknown-service")
    detected_at = incident.get("detected_at")
    base_time = datetime.fromisoformat(detected_at) if detected_at else datetime.now(timezone.utc)

    templates = _LOG_TEMPLATES.get(incident_type, _DEFAULT_TEMPLATES)[:count]
    logs = []
    for i, (level, message) in enumerate(templates):
        ts = base_time - timedelta(seconds=(len(templates) - i) * 5)
        logs.append(
            {
                "timestamp": ts.isoformat(),
                "level": level,
                "service": service,
                "message": message.format(service=service),
            }
        )
    return logs
