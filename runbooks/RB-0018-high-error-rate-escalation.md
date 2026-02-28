---
runbook_id: RB-0018
title: High Error Rate — General Escalation
service: all
severity_scope: HIGH, MED
tags: [error-rate, escalation, 5xx, latency]
first_action_step: Page on-call lead and enable enhanced logging on affected services.
---
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
# High Error Rate — General Escalation

## Overview
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
This runbook covers the general escalation procedure when any service reports
a sustained high 5xx error rate exceeding threshold. Use this alongside
service-specific runbooks for targeted remediation.

## Detection Signals
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
- CloudWatch alarm: `ErrorRate > 5%` on any service
- ALB target group: healthy host count drops
- Spike in 500/502/503/504 responses
- Increased latency P99 > 2x baseline

## Immediate Actions (First 5 Minutes)
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->

1. **Page on-call lead**
   - Use PagerDuty: escalate to `sre-oncall` rotation
   - Open war room in `#incidents` Slack channel
   - Post initial message with: service name, error rate, time of detection

2. **Enable enhanced logging**
   - Set log level to DEBUG on affected service via feature flag
   - CloudWatch Logs Insights query:
   ```
   fields @timestamp, @message
   | filter @message like /ERROR/
   | sort @timestamp desc
   | limit 50
   ```

3. **Check recent deployments**
   - Review deploy dashboard for changes in last 2 hours
   - Correlate deploy timestamp with error rate spike
   - If correlated, initiate rollback immediately

4. **Verify dependencies**
   - Check downstream service health endpoints
   - Verify database connectivity and query latency
   - Check third-party API status pages

## Escalation Thresholds
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
| Duration | Action |
|----------|--------|
| 0-5 min  | Page on-call SRE |
| 5-15 min | Page service team lead |
| 15+ min  | Page VP Engineering, consider customer comms |
| 30+ min  | Executive escalation |

## Rollback Procedure
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
```bash
# Identify current deployment
aws ecs describe-services --cluster production --services <service-name>

# Roll back to previous revision
aws ecs update-service \
  --cluster production \
  --service <service-name> \
  --task-definition <service-name>:PREVIOUS_REVISION \
  --force-new-deployment
```

## Verification
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
- Error rate returns to < 1%
- P99 latency within 20% of baseline
- No DLQ message accumulation
- Downstream services reporting healthy

## Post-Incident
<!-- iq:runbook_id=RB-0018 | title=High Error Rate — General Escalation | first_action_step=Page on-call lead and enable enhanced logging on affected services. -->
- File postmortem within 24 hours
- Update runbook with any new failure modes discovered
- Add monitoring for the root cause signal