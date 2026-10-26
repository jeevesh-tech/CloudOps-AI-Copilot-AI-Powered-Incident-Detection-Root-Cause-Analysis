import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.monitoring.monitor import evaluate_event, get_connection, load_rules


def _event(service, environment, metrics, timestamp="2026-01-01T00:00:00+00:00"):
    return {"timestamp": timestamp, "service": service, "environment": environment, "metrics": metrics}


class TestMonitor(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.conn = get_connection(self.db_path)
        self.rules = load_rules()

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_ok_to_alarm_transition(self):
        event = _event("svc", "env", {"ECSCPU": 95, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 100})
        alerts = evaluate_event(event, self.rules, self.conn)
        ecs_alerts = [a for a in alerts if a["alarm_name"] == "cloudops-ecs-cpu-high"]
        self.assertEqual(len(ecs_alerts), 1)
        self.assertEqual(ecs_alerts[0]["transition"], "OK_TO_ALARM")
        self.assertTrue(ecs_alerts[0]["trigger_incident"])

    def test_alarm_to_alarm_does_not_trigger_incident(self):
        event = _event("svc", "env", {"ECSCPU": 95, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 100})
        evaluate_event(event, self.rules, self.conn)  # first: OK -> ALARM
        alerts = evaluate_event(event, self.rules, self.conn)  # second: ALARM -> ALARM
        ecs_alerts = [a for a in alerts if a["alarm_name"] == "cloudops-ecs-cpu-high"]
        self.assertEqual(ecs_alerts[0]["transition"], "ALARM_TO_ALARM")
        self.assertFalse(ecs_alerts[0]["trigger_incident"])

    def test_alarm_to_ok_transition(self):
        breach = _event("svc", "env", {"ECSCPU": 95, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 100})
        healthy = _event("svc", "env", {"ECSCPU": 20, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 100})
        evaluate_event(breach, self.rules, self.conn)
        alerts = evaluate_event(healthy, self.rules, self.conn)
        ecs_alerts = [a for a in alerts if a["alarm_name"] == "cloudops-ecs-cpu-high"]
        self.assertEqual(ecs_alerts[0]["transition"], "ALARM_TO_OK")
        self.assertFalse(ecs_alerts[0]["trigger_incident"])

    def test_no_alert_when_ok_stays_ok(self):
        event = _event("svc", "env", {"ECSCPU": 20, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 100})
        alerts = evaluate_event(event, self.rules, self.conn)
        self.assertEqual(alerts, [])

    def test_each_metric_recorded_once_per_event(self):
        # AppLatency has two rules (high + low); ensure it's only logged once.
        event = _event("svc", "env", {"ECSCPU": 20, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 100})
        evaluate_event(event, self.rules, self.conn)
        rows = self.conn.execute("SELECT COUNT(*) FROM metrics_log WHERE metric='AppLatency'").fetchone()
        self.assertEqual(rows[0], 1)

    def test_low_latency_rule_triggers_separately_from_high(self):
        event = _event("svc", "env", {"ECSCPU": 20, "RDSConnections": 10, "ALB5xx": 0, "DeploymentRegression": 0, "AppLatency": 5})
        alerts = evaluate_event(event, self.rules, self.conn)
        low_alerts = [a for a in alerts if a["alarm_name"] == "cloudops-app-latency-low"]
        self.assertEqual(len(low_alerts), 1)
        self.assertTrue(low_alerts[0]["trigger_incident"])


if __name__ == "__main__":
    unittest.main()
