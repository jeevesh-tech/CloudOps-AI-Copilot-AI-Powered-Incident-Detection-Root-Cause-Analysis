# CloudOps AI Copilot (Phase 1 - Local)

Local-first reproduction of the CloudOps incident lifecycle, per architecture diagram.
Flow: Simulator -> Monitoring -> Incident Processor -> Investigation -> RAG -> Bedrock Agent -> AI Analysis -> Snowflake -> Dashboard.

## Status

All 14 planned steps complete. Full end-to-end flow (`python main.py run`) works, backed by
a real AWS Bedrock Agent (falls back to a stub if unconfigured) and a real Snowflake account.

## Setup

```
python -m pip install -r requirements.txt
```

### AWS Bedrock (optional - stub used if unset)

Bedrock Agents Classic is in maintenance mode and blocks new agent creation for
accounts with no prior usage, so this adapter calls a Bedrock foundation model
directly via bedrock-runtime's Converse API instead of the Agent wrapper:

```
set BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
set AWS_REGION=us-east-1
```

(Requires that model to be enabled under Bedrock > Model access in the AWS Console.)
Credentials come from the default AWS credential chain (environment variables,
~/.aws/credentials, SSO, or an assigned role) - never hardcoded.

### Snowflake (required for persistence; app runs fine without it, just skips writes)

```
set SNOWFLAKE_ACCOUNT=...
set SNOWFLAKE_USER=...
set SNOWFLAKE_PASSWORD=...          (or SNOWFLAKE_PRIVATE_KEY_PATH for key-pair auth)
set SNOWFLAKE_WAREHOUSE=...
set SNOWFLAKE_DATABASE=...
set SNOWFLAKE_SCHEMA=...
set SNOWFLAKE_ROLE=...              (optional)
```

Then, once per environment:

```
python main.py snowflake init
python main.py snowflake seed-knowledge
```

## Run

```
python main.py simulate [--scenario NAME] [--continuous] [--interval SECS] [--count N] [--seed N]
python main.py monitor [--scenario NAME] [--seed N]
python main.py incidents
python main.py investigate <incident_id>
python main.py analyze <incident_id>
python main.py dashboard [incident_id]
python main.py run [--scenario NAME] [--seed N]     # full end-to-end flow
```

## Tests

```
python -m unittest discover tests -v
```

No AWS or Snowflake connectivity required for tests (isolated temp SQLite DBs + mocks).

## Notes on Snowflake schema

`snowflake/schema.sql` defines INCIDENTS, METRICS, AI_ANALYSIS, KNOWLEDGE. If your Snowflake
account already has differently-shaped tables of the same name from an earlier prototype,
either use a dedicated schema for this project or align the existing tables to this schema
before running `python main.py snowflake init`.
