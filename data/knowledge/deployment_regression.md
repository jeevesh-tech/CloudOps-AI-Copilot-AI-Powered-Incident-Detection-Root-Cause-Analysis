---
incident_type: DEPLOYMENT_REGRESSION
title: Deployment Regression Runbook
tags: [deployment, regression, rollback, release]
---

# Deployment Regression

## Symptoms
- DeploymentRegression score elevated shortly after a release
- Correlated increase in latency and/or error rate immediately following a deployment
- Issue timing aligns closely with a recent rollout

## Likely Causes
- A code change introducing a performance regression or bug
- A configuration change deployed alongside the release
- A database migration causing lock contention or slow queries
- Incompatible dependency version introduced in the release

## Investigation Steps
1. Confirm the deployment timestamp and compare against when symptoms began.
2. Review the diff/changelog for the deployed version.
3. Check whether metrics (CPU, latency, 5xx) moved in lockstep with the deployment.
4. Check for accompanying database migrations or config changes.

## Recommended Actions
- Roll back to the previous stable version if regression is confirmed.
- If rollback is not immediately possible, apply a hotfix for the specific regression.
- Add or strengthen pre-deployment performance/regression testing to catch this earlier.
- Document the root cause and add a canary/rollout gate to reduce blast radius next time.
