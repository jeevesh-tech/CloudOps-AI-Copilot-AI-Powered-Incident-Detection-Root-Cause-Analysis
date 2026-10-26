import unittest

from app.rag.retriever import retrieve_runbooks, _load_index


class TestRag(unittest.TestCase):
    def setUp(self):
        _load_index(force_reload=True)

    def test_exact_incident_type_match_ranks_first(self):
        incident = {"incident_type": "ECS_CPU_HIGH", "reason": "ECS CPU exceeded threshold", "metric": "ECSCPU"}
        results = retrieve_runbooks(incident, top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["incident_type"], "ECS_CPU_HIGH")

    def test_all_known_incident_types_have_a_runbook(self):
        for incident_type in [
            "ECS_CPU_HIGH", "RDS_CONNECTION_EXHAUSTION", "ALB_5XX_SPIKE",
            "DEPLOYMENT_REGRESSION", "APP_LATENCY_HIGH", "APP_LATENCY_LOW",
        ]:
            incident = {"incident_type": incident_type, "reason": "", "metric": ""}
            results = retrieve_runbooks(incident, top_k=1)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["incident_type"], incident_type)

    def test_unknown_incident_type_returns_empty_or_fallback(self):
        incident = {"incident_type": "TOTALLY_UNKNOWN_XYZ", "reason": "", "metric": ""}
        results = retrieve_runbooks(incident, top_k=2)
        for r in results:
            self.assertNotEqual(r["incident_type"], "TOTALLY_UNKNOWN_XYZ")


if __name__ == "__main__":
    unittest.main()
