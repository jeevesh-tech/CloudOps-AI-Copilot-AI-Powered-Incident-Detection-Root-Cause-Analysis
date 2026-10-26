"""CloudOps AI Copilot - main entry point (Phase 1, local)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.simulator.simulator import SCENARIOS, SimulatorConfig, run_continuous, run_once
from app.monitoring.monitor import evaluate_event
from app.incidents.processor import process_alerts, list_incidents
from app.investigation.investigator import investigate
from app.ai.analyzer import analyze
from app.storage import snowflake_client
from app.rag.retriever import _load_index as load_runbook_index
from app.dashboard.dashboard import run as run_dashboard
from app.dashboard.web import run as run_web_dashboard

CONFIG_DIR = Path(__file__).resolve().parent / "config"


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.json", "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_simulate(args: argparse.Namespace) -> None:
    settings = load_settings()
    cfg = SimulatorConfig(
        service=settings.get("service", "payments-api"),
        environment=settings.get("environment", "simulation"),
        scenario=args.scenario,
        seed=args.seed,
        interval_seconds=args.interval,
        count=args.count,
    )
    if args.continuous:
        run_continuous(cfg)
    else:
        run_once(cfg)


def cmd_monitor(args: argparse.Namespace) -> None:
    settings = load_settings()
    cfg = SimulatorConfig(
        service=settings.get("service", "payments-api"),
        environment=settings.get("environment", "simulation"),
        scenario=args.scenario,
        seed=args.seed,
    )
    event = run_once(cfg)
    alerts = evaluate_event(event)
    if alerts:
        for alert in alerts:
            print(json.dumps(alert))
    else:
        print(json.dumps({"message": "No alarm-worthy transitions", "scenario": event["scenario"]}))

    snowflake_client.insert_metrics(event)

    incidents = process_alerts(alerts)
    for incident in incidents:
        print(json.dumps(incident))
        snowflake_client.insert_incident(incident)


def _run_pipeline_once(cfg: SimulatorConfig, show_dashboard: bool) -> list:
    """Run one pass of the full pipeline: Simulator -> Monitoring -> Incident Processor ->
    Investigation -> RAG -> AI Analysis -> Snowflake -> (optionally) Dashboard.
    Returns the list of incidents created this pass (may be empty)."""
    print(">> Step 1: Simulator")
    event = run_once(cfg)

    print("\n>> Step 2: Monitoring & Alert Engine")
    alerts = evaluate_event(event)
    if alerts:
        for alert in alerts:
            print(json.dumps(alert))
    else:
        print(f"No alarm-worthy transitions for scenario {event['scenario']}")
    snowflake_client.insert_metrics(event)

    print("\n>> Step 3: Incident Processor")
    incidents = process_alerts(alerts)
    if not incidents:
        print("No new incident created (either healthy metrics, or alarm already active - duplicate prevented).")
        return []
    for incident in incidents:
        print(json.dumps(incident))
        snowflake_client.insert_incident(incident)

    last_evidence = None
    last_analysis = None
    for incident in incidents:
        incident_id = incident["incident_id"]

        print(f"\n>> Step 4-5: Investigation Engine + Local RAG for {incident_id}")
        evidence = investigate(incident_id)
        print(f"Collected {len(evidence['logs'])} logs, {len(evidence['previous_incidents'])} previous incidents, "
              f"{len(evidence['runbooks'])} relevant runbook(s).")

        print(f"\n>> Step 6-7: AI Analysis for {incident_id}")
        analysis = analyze(evidence)
        print(json.dumps(analysis, indent=2))
        snowflake_client.insert_ai_analysis(analysis)

        if snowflake_client.is_configured():
            print(f"\n>> Step 8: Snowflake persistence complete for {incident_id}")
        else:
            print(f"\n>> Step 8: SKIPPED for {incident_id} - Snowflake env vars not set in this terminal session")

        last_evidence, last_analysis = evidence, analysis

    if show_dashboard:
        print("\n>> Step 9: Dashboard")
        # Reuse the evidence/analysis already computed above instead of recomputing -
        # avoids a redundant second AI provider call that could also return a different
        # (or failed) result than what was just persisted to Snowflake.
        run_dashboard(incidents[-1]["incident_id"], evidence=last_evidence, analysis=last_analysis)

    return incidents


def cmd_run(args: argparse.Namespace) -> None:
    settings = load_settings()
    cfg = SimulatorConfig(
        service=settings.get("service", "payments-api"),
        environment=settings.get("environment", "simulation"),
        scenario=args.scenario,
        seed=args.seed,
    )

    if not args.continuous:
        _run_pipeline_once(cfg, show_dashboard=True)
        return

    n = 0
    try:
        while args.count is None or n < args.count:
            n += 1
            ts = datetime.now(timezone.utc).isoformat()
            print(f"\n{'=' * 70}\n>> Iteration {n} at {ts}\n{'=' * 70}")
            _run_pipeline_once(cfg, show_dashboard=False)
            if args.count is None or n < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped continuous run.")


def cmd_incidents(args: argparse.Namespace) -> None:
    for incident in list_incidents():
        print(json.dumps(incident))


def cmd_investigate(args: argparse.Namespace) -> None:
    package = investigate(args.incident_id)
    if package is None:
        print(f"No incident found with id {args.incident_id}")
        return
    print(json.dumps(package, indent=2))


def cmd_analyze(args: argparse.Namespace) -> None:
    package = investigate(args.incident_id)
    if package is None:
        print(f"No incident found with id {args.incident_id}")
        return
    analysis = analyze(package)
    print(json.dumps(analysis, indent=2))
    snowflake_client.insert_ai_analysis(analysis)


def cmd_dashboard(args: argparse.Namespace) -> None:
    if args.web:
        print(f"Starting web dashboard at http://{args.host}:{args.port} ...")
        run_web_dashboard(host=args.host, port=args.port)
    else:
        run_dashboard(args.incident_id)


def cmd_snowflake_init(args: argparse.Namespace) -> None:
    snowflake_client.ensure_schema()
    print("Snowflake schema applied.")


def cmd_snowflake_seed_knowledge(args: argparse.Namespace) -> None:
    runbooks = load_runbook_index(force_reload=True)
    snowflake_client.insert_knowledge(runbooks)
    print(f"Seeded {len(runbooks)} runbooks into Snowflake KNOWLEDGE table.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="CloudOps AI Copilot (Phase 1, local)")
    subparsers = parser.add_subparsers(dest="command")

    p_sim = subparsers.add_parser("simulate", help="Generate synthetic incident telemetry")
    p_sim.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default=None,
        help="Scenario to simulate. Omit for random selection.",
    )
    p_sim.add_argument("--continuous", action="store_true", help="Run continuously instead of once")
    p_sim.add_argument("--interval", type=float, default=60.0, help="Seconds between events in continuous mode")
    p_sim.add_argument("--count", type=int, default=None, help="Number of events to generate in continuous mode (default: run forever)")
    p_sim.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    p_sim.set_defaults(func=cmd_simulate)

    p_mon = subparsers.add_parser("monitor", help="Generate one telemetry event and evaluate it against threshold rules")
    p_mon.add_argument("--scenario", choices=SCENARIOS, default=None, help="Scenario to simulate. Omit for random selection.")
    p_mon.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    p_mon.set_defaults(func=cmd_monitor)
    p_run = subparsers.add_parser("run", help="Run the complete end-to-end flow (Simulator -> ... -> Dashboard)")
    p_run.add_argument("--scenario", choices=SCENARIOS, default=None, help="Scenario to simulate. Omit for random selection.")
    p_run.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility (fixed scenario recommended if set)")
    p_run.add_argument("--continuous", action="store_true", help="Repeat the full pipeline every --interval seconds instead of running once")
    p_run.add_argument("--interval", type=float, default=60.0, help="Seconds between pipeline runs in continuous mode (default: 60)")
    p_run.add_argument("--count", type=int, default=None, help="Number of pipeline runs in continuous mode (default: run forever)")
    p_run.set_defaults(func=cmd_run)
    p_incidents = subparsers.add_parser("incidents", help="List stored incidents")
    p_incidents.set_defaults(func=cmd_incidents)
    p_dash = subparsers.add_parser("dashboard", help="Show the local CLI dashboard (all incidents, or one incident's detail)")
    p_dash.add_argument("incident_id", nargs="?", default=None, help="Show detail for this incident; omit to list all incidents")
    p_dash.add_argument("--web", action="store_true", help="Launch the web dashboard (Flask) instead of the CLI view")
    p_dash.add_argument("--host", default="127.0.0.1", help="Host to bind the web dashboard to (default: 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=5000, help="Port to bind the web dashboard to (default: 5000)")
    p_dash.set_defaults(func=cmd_dashboard)
    p_inv = subparsers.add_parser("investigate", help="Collect evidence for a specific incident")
    p_inv.add_argument("incident_id")
    p_inv.set_defaults(func=cmd_investigate)

    p_analyze = subparsers.add_parser("analyze", help="Investigate and run AI analysis for a specific incident")
    p_analyze.add_argument("incident_id")
    p_analyze.set_defaults(func=cmd_analyze)

    p_snowflake = subparsers.add_parser("snowflake", help="Snowflake maintenance commands")
    snowflake_sub = p_snowflake.add_subparsers(dest="snowflake_command")
    p_sf_init = snowflake_sub.add_parser("init", help="Apply snowflake/schema.sql")
    p_sf_init.set_defaults(func=cmd_snowflake_init)
    p_sf_seed = snowflake_sub.add_parser("seed-knowledge", help="Load local runbooks into the Snowflake KNOWLEDGE table")
    p_sf_seed.set_defaults(func=cmd_snowflake_seed_knowledge)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        return
    if not hasattr(args, "func"):
        print(f"Command '{args.command}' is not implemented yet. See README.md for progress.")
        return
    args.func(args)


if __name__ == "__main__":
    main()
