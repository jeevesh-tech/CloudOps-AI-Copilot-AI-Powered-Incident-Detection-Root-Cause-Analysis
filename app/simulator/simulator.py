"""
Incident Simulator.

Generates realistic synthetic telemetry for the CloudOps AI Copilot, standing in for
CloudWatch Metrics / real infrastructure in Phase 1 (local-only, no AWS dependency).

Future AWS mapping: this module's responsibility moves to an AWS Lambda function
(or a synthetic-canary approach) that publishes real CloudWatch metrics.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------
# Scenarios & metric model
# --------------------------------------------------------------------------

SCENARIOS = [
    "HEALTHY_BASELINE",
    "ECS_CPU_HIGH",
    "RDS_CONNECTION_EXHAUSTION",
    "ALB_5XX_SPIKE",
    "DEPLOYMENT_REGRESSION",
    "APP_LATENCY_HIGH",
    "APP_LATENCY_LOW",
]

METRIC_NAMES = [
    "ECSCPU",
    "RDSConnections",
    "ALB5xx",
    "DeploymentRegression",
    "AppLatency",
]

# Baseline (healthy) ranges for each metric.
_BASELINE_RANGES = {
    "ECSCPU": (20.0, 40.0),            # percent
    "RDSConnections": (10.0, 30.0),    # count (pool max assumed ~100)
    "ALB5xx": (0.0, 2.0),              # count per interval
    "DeploymentRegression": (0.0, 5.0),  # regression score 0-100
    "AppLatency": (80.0, 150.0),       # ms
}


def _baseline_metrics(rng: random.Random) -> dict:
    return {name: round(rng.uniform(*rng_range), 2) for name, rng_range in _BASELINE_RANGES.items()}


def _apply_scenario(scenario: str, metrics: dict, rng: random.Random) -> dict:
    """Mutate a baseline metric dict to reflect the given scenario."""
    if scenario == "HEALTHY_BASELINE":
        pass
    elif scenario == "ECS_CPU_HIGH":
        metrics["ECSCPU"] = round(rng.uniform(90.0, 99.5), 2)
    elif scenario == "RDS_CONNECTION_EXHAUSTION":
        metrics["RDSConnections"] = round(rng.uniform(90.0, 100.0), 2)
    elif scenario == "ALB_5XX_SPIKE":
        metrics["ALB5xx"] = round(rng.uniform(25.0, 120.0), 2)
    elif scenario == "DEPLOYMENT_REGRESSION":
        metrics["DeploymentRegression"] = round(rng.uniform(40.0, 95.0), 2)
        # A bad deployment commonly drags latency up too.
        metrics["AppLatency"] = round(rng.uniform(300.0, 600.0), 2)
    elif scenario == "APP_LATENCY_HIGH":
        metrics["AppLatency"] = round(rng.uniform(500.0, 1200.0), 2)
    elif scenario == "APP_LATENCY_LOW":
        # Abnormally low latency can indicate requests failing fast / short-circuiting
        # rather than being served correctly.
        metrics["AppLatency"] = round(rng.uniform(1.0, 15.0), 2)
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    return metrics


def generate_metrics(scenario: str, rng: Optional[random.Random] = None) -> dict:
    """Generate a single synthetic metric snapshot for the given scenario."""
    rng = rng or random
    metrics = _baseline_metrics(rng)
    return _apply_scenario(scenario, metrics, rng)


def generate_event(
    scenario: str,
    service: str,
    environment: str,
    rng: Optional[random.Random] = None,
) -> dict:
    """Generate one structured telemetry event (metrics + metadata) for a scenario."""
    rng = rng or random
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "environment": environment,
        "scenario": scenario,
        "metrics": generate_metrics(scenario, rng),
    }


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cloudops.simulator")
    if logger.handlers:
        return logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "simulator.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _log_event(event: dict) -> None:
    record = {
        "timestamp": event["timestamp"],
        "level": "INFO",
        "component": "simulator",
        "message": f"Generated scenario {event['scenario']}",
        "scenario": event["scenario"],
        "service": event["service"],
        "environment": event["environment"],
        "metrics": event["metrics"],
    }
    _get_logger().info(json.dumps(record))


# --------------------------------------------------------------------------
# Simulator driver
# --------------------------------------------------------------------------

@dataclass
class SimulatorConfig:
    service: str = "payments-api"
    environment: str = "simulation"
    scenario: Optional[str] = None       # None => random selection each tick
    seed: Optional[int] = None
    interval_seconds: float = 60.0
    count: Optional[int] = None          # None => run forever (continuous mode)


def _pick_scenario(cfg: SimulatorConfig, rng: random.Random) -> str:
    if cfg.scenario:
        if cfg.scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{cfg.scenario}'. Valid: {SCENARIOS}")
        return cfg.scenario
    return rng.choice(SCENARIOS)


def run_once(cfg: SimulatorConfig, rng: Optional[random.Random] = None) -> dict:
    """Generate and log a single telemetry event according to cfg."""
    rng = rng or random.Random(cfg.seed)
    scenario = _pick_scenario(cfg, rng)
    event = generate_event(scenario, cfg.service, cfg.environment, rng)
    _log_event(event)
    print(json.dumps(event))
    return event


def run_continuous(cfg: SimulatorConfig) -> list:
    """Repeatedly generate telemetry events until cfg.count is exhausted (or forever)."""
    rng = random.Random(cfg.seed)
    events = []
    n = 0
    try:
        while cfg.count is None or n < cfg.count:
            events.append(run_once(cfg, rng))
            n += 1
            if cfg.count is None or n < cfg.count:
                time.sleep(cfg.interval_seconds)
    except KeyboardInterrupt:
        pass
    return events
