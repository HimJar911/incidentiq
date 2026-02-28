---
runbook_id: RB-0007
title: Emergency Rollback Procedure
service: all
severity_scope: HIGH, MED, LOW
tags: [rollback, deployment, ecs, revert, emergency]
first_action_step: Identify the bad deployment revision and run the rollback command for the affected service.
---
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->
# Emergency Rollback Procedure

## Overview
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->
This runbook covers the standard emergency rollback procedure for any ECS service.
Use this when a recent deployment is identified as the root cause of an incident.

## When to Use This Runbook
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->
- Error rate spike correlated with a recent deployment
- Automated investigation identifies a suspect commit from the last 6 hours
- On-call lead makes the call to rollback rather than hotfix forward

## Pre-Rollback Checklist
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->
- [ ] Confirm deployment timestamp correlates with incident start
- [ ] Identify the previous stable task definition revision
- [ ] Notify team in `#incidents` that rollback is starting
- [ ] Confirm no database migrations were included (migrations cannot be rolled back automatically)

## Rollback Steps
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->

### 1. Identify current and previous revisions
```bash
# List recent task definition revisions
aws ecs list-task-definitions \
  --family-prefix <service-name> \
  --sort DESC \
  --max-items 5

# Get current running revision
aws ecs describe-services \
  --cluster production \
  --services <service-name> \
  --query 'services[0].taskDefinition'
```

### 2. Execute rollback
```bash
# Roll back to previous revision (current - 1)
CURRENT_REVISION=$(aws ecs describe-services \
  --cluster production \
  --services <service-name> \
  --query 'services[0].taskDefinition' \
  --output text | grep -o '[0-9]*$')

PREVIOUS_REVISION=$((CURRENT_REVISION - 1))

aws ecs update-service \
  --cluster production \
  --service <service-name> \
  --task-definition <service-name>:$PREVIOUS_REVISION \
  --force-new-deployment
```

### 3. Monitor rollback progress
```bash
# Wait for service to stabilize
aws ecs wait services-stable \
  --cluster production \
  --services <service-name>

echo "Rollback complete"
```

### 4. Verify health after rollback
```bash
# Check service health endpoint
curl -f https://api.company.com/<service>/health

# Check error rate (allow 2-3 minutes to stabilize)
aws cloudwatch get-metric-statistics \
  --namespace IncidentIQ/Demo \
  --metric-name ErrorRate \
  --dimensions Name=Service,Value=<service-name> \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average
```

## Service-Specific Notes
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->
| Service | Migration Risk | Rollback Time | Owner |
|---------|---------------|---------------|-------|
| payments-service | HIGH — always check | ~3 min | payments-team |
| auth-service | MED — check token schema | ~2 min | auth-team |
| user-service | LOW | ~2 min | platform-team |
| api-gateway | NONE | ~1 min | platform-team |

## Post-Rollback
<!-- iq:runbook_id=RB-0007 | title=Emergency Rollback Procedure | first_action_step=Identify the bad deployment revision and run the rollback command for the affected service. -->
- Confirm error rate returned to baseline
- Notify team in `#incidents` that rollback is complete
- Create hotfix branch — do not re-deploy the same commit
- Schedule postmortem within 24 hours