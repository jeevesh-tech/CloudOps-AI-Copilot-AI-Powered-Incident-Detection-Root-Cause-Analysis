-- CloudOps AI Copilot - Snowflake schema (Phase 1 persistent data platform)
-- Run once per database/schema to provision. Safe to re-run (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS INCIDENTS (
    incident_id      STRING PRIMARY KEY,
    alarm_name       STRING NOT NULL,
    incident_type    STRING NOT NULL,
    severity         STRING NOT NULL,
    state            STRING NOT NULL,
    reason           STRING NOT NULL,
    service          STRING NOT NULL,
    environment      STRING NOT NULL,
    metric           STRING NOT NULL,
    value            FLOAT NOT NULL,
    threshold        FLOAT NOT NULL,
    detected_at      TIMESTAMP_TZ NOT NULL,
    inserted_at      TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS METRICS (
    id               STRING DEFAULT UUID_STRING() PRIMARY KEY,
    recorded_at      TIMESTAMP_TZ NOT NULL,
    service          STRING NOT NULL,
    environment      STRING NOT NULL,
    metric           STRING NOT NULL,
    value            FLOAT NOT NULL,
    inserted_at      TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS AI_ANALYSIS (
    id               STRING DEFAULT UUID_STRING() PRIMARY KEY,
    incident_id      STRING NOT NULL,
    root_cause       STRING,
    confidence       FLOAT,
    severity         STRING,
    recommendations  VARIANT,
    next_steps       VARIANT,
    analyzed_at      TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS KNOWLEDGE (
    id               STRING DEFAULT UUID_STRING() PRIMARY KEY,
    incident_type    STRING,
    title            STRING NOT NULL,
    tags             VARIANT,
    content          STRING NOT NULL,
    path             STRING,
    inserted_at      TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);
