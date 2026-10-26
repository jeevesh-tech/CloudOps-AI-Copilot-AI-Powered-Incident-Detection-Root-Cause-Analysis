"""
AI model adapter.

Primary path: AWS Bedrock, per the architecture. Originally designed against Bedrock
Agents (bedrock-agent-runtime.invoke_agent); AWS put "Bedrock Agents Classic" into
maintenance mode and blocks new agent creation for accounts with no prior usage, so
this adapter calls a Bedrock foundation model directly via the bedrock-runtime
Converse API instead - still "AWS Bedrock for AI analysis," just without the retired
Agent resource wrapper.

Temporary fallback: while this AWS account's Bedrock access is blocked by an
account-level restriction (confirmed via AWS's own Playground failing identically -
not a code/config issue on our end), this adapter can call Google Gemini or Anthropic
directly instead, via GEMINI_API_KEY or ANTHROPIC_API_KEY. This is meant to be
temporary - swap back to Bedrock by unsetting those and setting BEDROCK_MODEL_ID once
AWS clears the account restriction. No other code needed to change either way (Step
17: loosely coupled AI adapter) - the public interface (invoke_agent(request_text,
session_id) -> str) is the same regardless of which provider actually serves the
request.

Credentials are never hardcoded here - AWS creds come from boto3's default credential
chain; the Gemini/Anthropic keys come from the GEMINI_API_KEY/ANTHROPIC_API_KEY
environment variables.

If neither is configured, this adapter falls back to a local stub response so the rest
of the pipeline can be built and tested end-to-end without any AI provider access.
"""

from __future__ import annotations

import json
import os
from typing import Optional


class BedrockAgentError(Exception):
    pass


def _stub_response(request_text: str) -> str:
    """Local fallback used when no AI provider is configured (dev/testing only)."""
    return json.dumps(
        {
            "root_cause": "STUB RESPONSE (no AI provider configured) - "
                          "set GEMINI_API_KEY, ANTHROPIC_API_KEY, or BEDROCK_MODEL_ID to call a real model.",
            "confidence": 0.0,
            "severity": "UNKNOWN",
            "recommendations": ["Configure a Gemini/Anthropic API key or Bedrock model to get real analysis."],
            "next_steps": ["Set GEMINI_API_KEY, ANTHROPIC_API_KEY, or BEDROCK_MODEL_ID environment variable."],
        }
    )


def _invoke_gemini(request_text: str) -> str:
    from google import genai  # imported lazily so it's only required when this path is used

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

    try:
        response = client.models.generate_content(model=model, contents=request_text)
    except Exception as exc:  # noqa: BLE001 - surface any SDK/API error uniformly
        raise BedrockAgentError(f"Gemini API invocation failed: {exc}") from exc

    try:
        return response.text
    except AttributeError as exc:
        raise BedrockAgentError(f"Unexpected Gemini response shape: {response}") from exc


def _invoke_anthropic(request_text: str) -> str:
    import anthropic  # imported lazily so it's only required when this path is used

    client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from the environment
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": request_text}],
        )
    except Exception as exc:  # noqa: BLE001 - surface any SDK/API error uniformly
        raise BedrockAgentError(f"Anthropic API invocation failed: {exc}") from exc

    try:
        return response.content[0].text
    except (IndexError, AttributeError) as exc:
        raise BedrockAgentError(f"Unexpected Anthropic response shape: {response}") from exc


def _invoke_bedrock(request_text: str, model_id: str) -> str:
    import boto3  # imported lazily so boto3 is only required once a model is configured

    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    client = boto3.client("bedrock-runtime", region_name=region)

    try:
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": request_text}]}],
        )
    except Exception as exc:  # noqa: BLE001 - surface any boto3/AWS error uniformly
        raise BedrockAgentError(f"Bedrock model invocation failed: {exc}") from exc

    try:
        return response["output"]["message"]["content"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise BedrockAgentError(f"Unexpected Bedrock response shape: {response}") from exc


def invoke_agent(request_text: str, session_id: Optional[str] = None) -> str:
    """
    Invoke the configured AI provider with the given input text, returning its raw
    text response. Preference order: Gemini (genuinely free tier, no billing needed)
    -> Anthropic (needs paid credit) -> Bedrock (blocked pending AWS account
    verification) -> local stub if none are configured.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return _invoke_gemini(request_text)

    if os.environ.get("ANTHROPIC_API_KEY"):
        return _invoke_anthropic(request_text)

    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if model_id:
        return _invoke_bedrock(request_text, model_id)

    return _stub_response(request_text)
