---
incident_type: ECS_CPU_HIGH
title: ECS CPU High Runbook
tags: [ecs, cpu, autoscaling, fargate]
---

# ECS CPU High

## Symptoms
- ECSCPU metric sustained above 90% utilization
- Increasing request latency under load
- Possible task-level throttling

## Likely Causes
- Traffic spike beyond current task count / scaling policy capacity
- A recent deployment introducing a CPU-intensive regression
- Insufficient task CPU reservation for the workload
- A runaway process or infinite loop in application code

## Investigation Steps
1. Check ECS service desired vs. running task count and recent scaling activity.
2. Compare CPU utilization trend against request volume (ALB request count).
3. Check whether a deployment occurred shortly before the CPU spike.
4. Review application logs for unusual processing patterns during the spike window.

## Recommended Actions
- Manually scale out the ECS service if auto-scaling has not yet reacted.
- If correlated with a recent deployment, consider rolling back.
- Increase task CPU allocation if the workload has structurally grown.
- Profile the application for CPU hotspots if no external cause is found.
