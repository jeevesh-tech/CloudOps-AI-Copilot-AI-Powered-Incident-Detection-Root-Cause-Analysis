"""Evidence package assembly for the Investigation Engine."""

from __future__ import annotations


def build_evidence_package(
    incident: dict,
    metrics: dict,
    metric_history: list,
    logs: list,
    deployment: dict,
    previous_incidents: list,
    runbooks: list,
) -> dict:
    return {
        "incident_id": incident["incident_id"],
        "incident_type": incident["incident_type"],
        "severity": incident["severity"],
        "service": incident["service"],
        "environment": incident["environment"],
        "reason": incident["reason"],
        "metrics": metrics,
        "metric_history": metric_history,
        "logs": logs,
        "deployment": deployment,
        "previous_incidents": previous_incidents,
        "runbooks": runbooks,
    }
