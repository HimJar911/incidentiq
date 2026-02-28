---
runbook_id: RB-0042
title: Payment Gateway Timeout Recovery
service: payments-service
severity_scope: HIGH, MED
tags: [payments, gateway, timeout, latency]
first_action_step: Check payment gateway config for recent changes and roll back if needed.
---
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
# Payment Gateway Timeout Recovery

## Overview
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
This runbook covers recovery procedures when the payments-service reports elevated
timeout errors or latency spikes from the payment gateway integration.

## Detection Signals
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
- CloudWatch alarm: `payments-service ErrorRate > 5%`
- Dashboard: Payment success rate drops below 95%
- Spike in 504/503 responses from `/api/payments/*` endpoints
- Datadog monitor: `payments.gateway.timeout.count > 10/min`

## Immediate Actions (First 5 Minutes)
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->

1. **Check recent config changes**
   - Review deploy dashboard for changes to `services/payments/` in the last 6 hours
   - Specifically check: `gateway.py`, `config.py`, timeout and retry settings
   - If a config change is identified, initiate rollback immediately

2. **Verify gateway health**
   - Check Stripe/Adyen status page for upstream issues
   - Test gateway connectivity: `curl -v https://api.stripe.com/v1/health`
   - Check internal gateway proxy health endpoint: `GET /internal/gateway/health`

3. **Enable circuit breaker (if timeout > 30s)**
   - SSH to payments-service instances or use ECS exec
   - Set env var: `GATEWAY_CIRCUIT_BREAKER_ENABLED=true`
   - This degrades gracefully by queuing payment retries instead of blocking

4. **Check connection pool exhaustion**
   - CloudWatch metric: `payments-service.db.connection_pool_exhausted`
   - If > 0, restart the service pods to reset pool state

## Escalation
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
- Page **payments-team on-call lead** immediately for HIGH severity
- Notify **VP Engineering** if duration > 15 minutes
- Open a war room in **#incidents** Slack channel

## Rollback Procedure
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
```bash
# Get last known good deployment
aws ecs describe-services --cluster production --services payments-service

# Rollback to previous task definition
aws ecs update-service \
  --cluster production \
  --service payments-service \
  --task-definition payments-service:PREVIOUS_REVISION \
  --force-new-deployment
```

## Verification
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
After remediation, confirm:
- Error rate returns to < 1%
- P99 latency returns to < 500ms
- Payment success rate > 99%
- No pending retry queue buildup

## Post-Incident
<!-- iq:runbook_id=RB-0042 | title=Payment Gateway Timeout Recovery | first_action_step=Check payment gateway config for recent changes and roll back if needed. -->
- File postmortem within 24 hours
- Update gateway timeout values in config if they contributed
- Add regression test for the failure mode
