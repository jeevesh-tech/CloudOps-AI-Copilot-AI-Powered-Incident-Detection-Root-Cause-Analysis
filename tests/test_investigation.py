import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import app.incidents.processor as processor
import app.investigation.metrics as inv_metrics
from app.investigation.logs import collect_logs
from app.investigation.deployments import get_deployment_info
from app.investigation.evidence import build_evidence_package


class TestInvestigationHelpers(unittest.TestCase):
    def test_collect_logs_correlates_with_incident_type(self):
        incident = {"incident_type": "RDS_CONNECTION_EXHAUSTION", "service": "svc", "detected_at": "2026-01-01T00:00:00+00:00"}
        logs = collect_logs(incident)
        self.assertTrue(any("connection" in log["message"].lower() for log in logs))

    def test_collect_logs_unknown_type_uses_default_template(self):
        incident = {"incident_type": "NOT_REAL", "service": "svc", "detected_at": "2026-01-01T00:00:00+00:00"}
        logs = collect_logs(incident)
        self.assertEqual(len(logs), 1)

    def test_deployment_flags_likely_contributor_for_regression(self):
        incident = {"incident_type": "DEPLOYMENT_REGRESSION", "service": "svc", "detected_at": "2026-01-01T00:00:00+00:00"}
        dep = get_deployment_info(incident)
        self.assertTrue(dep["likely_contributor"])

    def test_deployment_not_flagged_for_other_types(self):
        incident = {"incident_type": "ECS_CPU_HIGH", "service": "svc", "detected_at": "2026-01-01T00:00:00+00:00"}
        dep = get_deployment_info(incident)
        self.assertFalse(dep["likely_contributor"])

    def test_build_evidence_package_shape(self):
        incident = {
            "incident_id": "INC-1", "incident_type": "ECS_CPU_HIGH", "severity": "HIGH",
            "service": "svc", "environment": "env", "reason": "r",
        }
        package = build_evidence_package(incident, {}, [], [], {}, [], [])
        for key in ["incident_id", "incident_type", "metrics", "metric_history", "logs", "deployment", "previous_incidents", "runbooks"]:
            self.assertIn(key, package)


class TestMetricHistory(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.patcher = mock.patch.object(processor, "DB_PATH", self.db_path)
        self.patcher.start()
        self.metrics_patcher = mock.patch.object(inv_metrics, "DB_PATH", self.db_path)
        self.metrics_patcher.start()

        conn = processor.get_connection()
        import app.monitoring.monitor as monitor
        monitor_patcher = mock.patch.object(monitor, "DB_PATH", self.db_path)
        monitor_patcher.start()
        self.addCleanup(monitor_patcher.stop)
        self.monitor = monitor
        conn.close()

    def tearDown(self):
        self.patcher.stop()
        self.metrics_patcher.stop()
        self._tmpdir.cleanup()

    def test_current_metrics_returns_latest_value(self):
        conn = self.monitor.get_connection(self.db_path)
        event = {"timestamp": "2026-01-01T00:00:00+00:00", "service": "svc", "environment": "env",
                  "metrics": {"ECSCPU": 50}}
        self.monitor.evaluate_event(event, self.monitor.load_rules(), conn)
        event2 = {"timestamp": "2026-01-01T00:01:00+00:00", "service": "svc", "environment": "env",
                   "metrics": {"ECSCPU": 60}}
        self.monitor.evaluate_event(event2, self.monitor.load_rules(), conn)
        conn.close()

        current = inv_metrics.current_metrics("svc", "env")
        self.assertEqual(current["ECSCPU"], 60)

    def test_metrics_at_timestamp_ignores_later_unrelated_events(self):
        conn = self.monitor.get_connection(self.db_path)
        event = {"timestamp": "2026-01-01T00:00:00+00:00", "service": "svc", "environment": "env",
                  "metrics": {"ECSCPU": 95, "ALB5xx": 0}}
        self.monitor.evaluate_event(event, self.monitor.load_rules(), conn)
        # A later, unrelated event for the same service must not contaminate the
        # evidence for the earlier incident.
        later_event = {"timestamp": "2026-01-01T00:05:00+00:00", "service": "svc", "environment": "env",
                        "metrics": {"ECSCPU": 20, "ALB5xx": 111.36}}
        self.monitor.evaluate_event(later_event, self.monitor.load_rules(), conn)
        conn.close()

        snapshot = inv_metrics.metrics_at_timestamp("svc", "env", "2026-01-01T00:00:00+00:00")
        self.assertEqual(snapshot["ECSCPU"], 95)
        self.assertEqual(snapshot["ALB5xx"], 0)


if __name__ == "__main__":
    unittest.main()
