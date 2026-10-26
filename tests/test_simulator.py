import unittest

from app.simulator.simulator import SCENARIOS, generate_event, generate_metrics


class TestSimulator(unittest.TestCase):
    def test_healthy_baseline_metrics_within_range(self):
        metrics = generate_metrics("HEALTHY_BASELINE")
        self.assertLess(metrics["ECSCPU"], 90)
        self.assertLess(metrics["RDSConnections"], 90)
        self.assertLess(metrics["ALB5xx"], 20)
        self.assertLess(metrics["DeploymentRegression"], 40)
        self.assertTrue(20 < metrics["AppLatency"] < 500)

    def test_ecs_cpu_high_breaches_threshold(self):
        metrics = generate_metrics("ECS_CPU_HIGH")
        self.assertGreaterEqual(metrics["ECSCPU"], 90)

    def test_rds_connection_exhaustion_breaches_threshold(self):
        metrics = generate_metrics("RDS_CONNECTION_EXHAUSTION")
        self.assertGreaterEqual(metrics["RDSConnections"], 90)

    def test_alb_5xx_spike_breaches_threshold(self):
        metrics = generate_metrics("ALB_5XX_SPIKE")
        self.assertGreaterEqual(metrics["ALB5xx"], 20)

    def test_deployment_regression_breaches_threshold(self):
        metrics = generate_metrics("DEPLOYMENT_REGRESSION")
        self.assertGreaterEqual(metrics["DeploymentRegression"], 40)

    def test_app_latency_high_breaches_threshold(self):
        metrics = generate_metrics("APP_LATENCY_HIGH")
        self.assertGreaterEqual(metrics["AppLatency"], 500)

    def test_app_latency_low_breaches_threshold(self):
        metrics = generate_metrics("APP_LATENCY_LOW")
        self.assertLessEqual(metrics["AppLatency"], 20)

    def test_all_scenarios_produce_all_metrics(self):
        for scenario in SCENARIOS:
            event = generate_event(scenario, "svc", "env")
            self.assertEqual(event["scenario"], scenario)
            for metric in ["ECSCPU", "RDSConnections", "ALB5xx", "DeploymentRegression", "AppLatency"]:
                self.assertIn(metric, event["metrics"])

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            generate_metrics("NOT_A_SCENARIO")


if __name__ == "__main__":
    unittest.main()
