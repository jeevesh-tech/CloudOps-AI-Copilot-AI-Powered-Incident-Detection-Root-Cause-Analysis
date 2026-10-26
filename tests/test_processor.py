import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.incidents.processor import get_connection, process_alert, process_alerts, get_incident


def _alert(trigger=True, alarm_name="cloudops-ecs-cpu-high"):
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "alarm_name": alarm_name,
        "service": "svc",
        "environment": "env",
        "metric": "ECSCPU",
        "value": 95,
        "threshold": 90,
        "incident_type": "ECS_CPU_HIGH",
        "severity": "HIGH",
        "reason": "ECS CPU exceeded threshold",
        "transition": "OK_TO_ALARM" if trigger else "ALARM_TO_ALARM",
        "trigger_incident": trigger,
    }


class TestProcessor(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.conn = get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_trigger_incident_creates_incident(self):
        incident = process_alert(_alert(trigger=True), self.conn)
        self.assertIsNotNone(incident)
        self.assertEqual(incident["incident_id"], "INC-000001")
        self.assertEqual(incident["incident_type"], "ECS_CPU_HIGH")

    def test_non_trigger_alert_creates_no_incident(self):
        incident = process_alert(_alert(trigger=False), self.conn)
        self.assertIsNone(incident)

    def test_incident_ids_are_sequential_and_unique(self):
        i1 = process_alert(_alert(trigger=True), self.conn)
        i2 = process_alert(_alert(trigger=True), self.conn)
        self.assertEqual(i1["incident_id"], "INC-000001")
        self.assertEqual(i2["incident_id"], "INC-000002")

    def test_get_incident_round_trips(self):
        created = process_alert(_alert(trigger=True), self.conn)
        fetched = get_incident(created["incident_id"], self.conn)
        self.assertEqual(fetched["incident_id"], created["incident_id"])

    def test_process_alerts_batch_only_creates_for_triggers(self):
        alerts = [_alert(trigger=True), _alert(trigger=False), _alert(trigger=True)]
        incidents = process_alerts(alerts, self.conn)
        self.assertEqual(len(incidents), 2)


if __name__ == "__main__":
    unittest.main()
