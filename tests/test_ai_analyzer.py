import json
import unittest
from unittest import mock

from app.ai.analyzer import analyze, build_request_text, _parse_response


def _evidence():
    return {
        "incident_id": "INC-1",
        "incident_type": "ECS_CPU_HIGH",
        "severity": "HIGH",
        "service": "svc",
        "environment": "env",
        "reason": "ECS CPU exceeded threshold",
        "metrics": {"ECSCPU": 95},
        "metric_history": [],
        "logs": [],
        "deployment": {},
        "previous_incidents": [],
        "runbooks": [{"title": "ECS CPU High Runbook", "content": "do X"}],
    }


class TestAiAnalyzer(unittest.TestCase):
    def test_parse_valid_json_response(self):
        raw = json.dumps({
            "root_cause": "CPU spike",
            "confidence": 0.9,
            "severity": "HIGH",
            "recommendations": ["scale out"],
            "next_steps": ["monitor"],
        })
        result = _parse_response(raw)
        self.assertEqual(result["root_cause"], "CPU spike")
        self.assertEqual(result["confidence"], 0.9)
        self.assertEqual(result["recommendations"], ["scale out"])

    def test_parse_json_wrapped_in_markdown_code_fence(self):
        fenced = "```json\n" + json.dumps({
            "root_cause": "CPU exhaustion",
            "confidence": 0.92,
            "severity": "HIGH",
            "recommendations": ["Scale out"],
            "next_steps": ["Monitor"],
        }) + "\n```"
        result = _parse_response(fenced)
        self.assertEqual(result["root_cause"], "CPU exhaustion")
        self.assertEqual(result["confidence"], 0.92)

    def test_parse_invalid_json_falls_back_gracefully(self):
        result = _parse_response("not json at all")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["severity"], "UNKNOWN")
        self.assertIn("raw_response", result)

    def test_parse_missing_fields_defaults(self):
        result = _parse_response(json.dumps({"root_cause": "X"}))
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["next_steps"], [])
        self.assertEqual(result["confidence"], 0.0)

    def test_build_request_text_includes_incident_and_runbook(self):
        text = build_request_text(_evidence())
        self.assertIn("INC-1", text)
        self.assertIn("ECS CPU High Runbook", text)

    def test_analyze_uses_stub_when_bedrock_unconfigured(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            analysis = analyze(_evidence())
        self.assertEqual(analysis["incident_id"], "INC-1")
        self.assertIn("STUB RESPONSE", analysis["root_cause"])

    def test_analyze_parses_mocked_agent_response(self):
        mocked_response = json.dumps({
            "root_cause": "Deployment regression",
            "confidence": 0.87,
            "severity": "HIGH",
            "recommendations": ["Roll back"],
            "next_steps": ["Monitor error rate"],
        })
        with mock.patch("app.ai.analyzer.invoke_agent", return_value=mocked_response):
            analysis = analyze(_evidence())
        self.assertEqual(analysis["root_cause"], "Deployment regression")
        self.assertEqual(analysis["confidence"], 0.87)
        self.assertEqual(analysis["recommendations"], ["Roll back"])


if __name__ == "__main__":
    unittest.main()
