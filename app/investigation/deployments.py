"""
Simulated deployment information for the Investigation Engine.

Phase 1 has no real CI/CD pipeline to query, so this module reports a plausible
synthetic "last deployment" record, flagging it as a likely contributor when the
incident type is DEPLOYMENT_REGRESSION. Future AWS mapping: query CodeDeploy /
CodePipeline (or equivalent) deployment history for the service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def get_deployment_info(incident: dict) -> dict:
    service = incident.get("service", "unknown-service")
    incident_type = incident.get("incident_type")
    detected_at = incident.get("detected_at")
    base_time = datetime.fromisoformat(detected_at) if detected_at else datetime.now(timezone.utc)

    if incident_type == "DEPLOYMENT_REGRESSION":
        deployed_at = base_time - timedelta(minutes=8)
        return {
            "service": service,
            "version": "v-next",
            "deployed_at": deployed_at.isoformat(),
            "minutes_before_incident": 8,
            "likely_contributor": True,
        }

    deployed_at = base_time - timedelta(hours=6)
    return {
        "service": service,
        "version": "v-stable",
        "deployed_at": deployed_at.isoformat(),
        "minutes_before_incident": 360,
        "likely_contributor": False,
    }
