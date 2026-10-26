-- CloudOps AI Copilot - verification queries
-- Run in Snowsight: select all lines, then click Run (running with cursor on one
-- line only executes that single statement).

USE DATABASE CLOUDOPS_AI;
USE SCHEMA CLOUDOPS_PHASE1;

-- Row counts across all four tables
SELECT 'INCIDENTS' AS table_name, COUNT(*) AS row_count FROM INCIDENTS
UNION ALL
SELECT 'METRICS', COUNT(*) FROM METRICS
UNION ALL
SELECT 'AI_ANALYSIS', COUNT(*) FROM AI_ANALYSIS
UNION ALL
SELECT 'KNOWLEDGE', COUNT(*) FROM KNOWLEDGE;

-- All incidents, newest first
SELECT incident_id, incident_type, severity, state, service, environment,
       metric, value, threshold, detected_at
FROM INCIDENTS
ORDER BY detected_at DESC;

-- Latest 30 metric readings
SELECT recorded_at, service, environment, metric, value
FROM METRICS
ORDER BY recorded_at DESC
LIMIT 30;

-- All AI analysis records, newest first
SELECT incident_id, root_cause, confidence, severity, recommendations, next_steps, analyzed_at
FROM AI_ANALYSIS
ORDER BY analyzed_at DESC;

-- All seeded runbooks
SELECT incident_type, title, tags, path
FROM KNOWLEDGE
ORDER BY incident_type;

-- Incidents that do NOT yet have an AI analysis (useful to spot gaps)
SELECT i.incident_id, i.incident_type, i.detected_at
FROM INCIDENTS i
LEFT JOIN AI_ANALYSIS a ON a.incident_id = i.incident_id
WHERE a.incident_id IS NULL
ORDER BY i.detected_at DESC;

-- Incident count by type and severity
SELECT incident_type, severity, COUNT(*) AS occurrences
FROM INCIDENTS
GROUP BY incident_type, severity
ORDER BY occurrences DESC;
