"""
Local Dashboard (CLI).

Per company-laptop restrictions, this is a CLI-first dashboard using only stdlib -
no Streamlit/Flask required. Data access goes through the same modules the rest of
the pipeline uses (incidents.processor, investigation.investigator, ai.analyzer),
so a future web UI can reuse this module's `gather_dashboard_data` function without
duplicating logic.

Future AWS mapping: this becomes an Amplify-hosted web frontend, likely querying
Snowflake directly rather than local SQLite.
"""

from __future__ import annotations

import json

from app.incidents.processor import list_incidents, get_incident
from app.investigation.investigator import investigate
from app.ai.analyzer import analyze


def gather_dashboard_data(incident_id: str, evidence: dict = None, analysis: dict = None) -> dict:
    """
    Assemble everything the dashboard needs to display for one incident.

    If the caller already computed `evidence` and/or `analysis` (e.g. the main pipeline,
    right after running investigate()/analyze() for this same incident), pass them in to
    avoid a redundant second AI provider call - each analyze() call costs real API usage
    and can also produce a different result on retry, which would confusingly show a
    different analysis than the one already persisted to Snowflake.
    """
    incident = get_incident(incident_id)
    if not incident:
        return {}
    if evidence is None:
        evidence = investigate(incident_id) or {}
    if analysis is None:
        analysis = analyze(evidence) if evidence else {}
    return {"incident": incident, "evidence": evidence, "analysis": analysis}


def _print_header(text: str) -> None:
    print("=" * len(text))
    print(text)
    print("=" * len(text))


def render_incident_list() -> None:
    incidents = list_incidents()
    _print_header("CloudOps AI Copilot - Active Incidents")
    if not incidents:
        print("No incidents recorded.")
        return

    high = sum(1 for i in incidents if i["severity"] == "HIGH")
    medium = sum(1 for i in incidents if i["severity"] == "MEDIUM")
    low = sum(1 for i in incidents if i["severity"] == "LOW")
    print(f"HIGH: {high}   MEDIUM: {medium}   LOW: {low}   TOTAL: {len(incidents)}\n")

    print(f"{'INCIDENT ID':<14}{'TYPE':<28}{'STATE':<8}{'SEVERITY':<10}{'DETECTED AT'}")
    print("-" * 90)
    for inc in incidents:
        print(f"{inc['incident_id']:<14}{inc['incident_type']:<28}{inc['state']:<8}{inc['severity']:<10}{inc['detected_at']}")


def render_incident_detail(incident_id: str, evidence: dict = None, analysis: dict = None) -> None:
    data = gather_dashboard_data(incident_id, evidence=evidence, analysis=analysis)
    if not data:
        print(f"No incident found with id {incident_id}")
        return

    incident = data["incident"]
    evidence = data["evidence"]
    analysis = data["analysis"]

    _print_header(f"Incident {incident_id} - {incident['incident_type']}")
    print(f"Severity:    {incident['severity']}")
    print(f"State:       {incident['state']}")
    print(f"Service:     {incident['service']} ({incident['environment']})")
    print(f"Reason:      {incident['reason']}")
    print(f"Detected at: {incident['detected_at']}")

    print("\n-- Current Metrics --")
    for metric, value in evidence.get("metrics", {}).items():
        print(f"  {metric}: {value}")

    print("\n-- Recent Logs --")
    for log in evidence.get("logs", []):
        print(f"  [{log['level']}] {log['timestamp']}  {log['message']}")

    print("\n-- Deployment --")
    dep = evidence.get("deployment", {})
    print(f"  version={dep.get('version')} deployed_at={dep.get('deployed_at')} likely_contributor={dep.get('likely_contributor')}")

    print("\n-- Previous Incidents (same service) --")
    prev = evidence.get("previous_incidents", [])
    if not prev:
        print("  None")
    for p in prev:
        print(f"  {p['incident_id']} - {p['incident_type']} ({p['detected_at']})")

    print("\n-- Relevant Runbooks --")
    for rb in evidence.get("runbooks", []):
        print(f"  {rb['title']} ({rb['path']})")

    print("\n-- AI Analysis --")
    print(f"  Root cause:  {analysis.get('root_cause')}")
    print(f"  Confidence:  {analysis.get('confidence')}")
    print(f"  Severity:    {analysis.get('severity')}")
    print("  Recommendations:")
    for r in analysis.get("recommendations", []):
        print(f"    - {r}")
    print("  Next steps:")
    for s in analysis.get("next_steps", []):
        print(f"    - {s}")


def run(incident_id: str = None, evidence: dict = None, analysis: dict = None) -> None:
    if incident_id:
        render_incident_detail(incident_id, evidence=evidence, analysis=analysis)
    else:
        render_incident_list()
