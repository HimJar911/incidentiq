---
runbook_id: RB-0031
title: Auth Service Degradation
service: auth-service
severity_scope: HIGH, MED
tags: [auth, authentication, tokens, session, degradation]
first_action_step: Check auth service token validation latency and recent middleware changes.
---

# Auth Service Degradation

## Overview
This runbook covers recovery procedures when the auth-service reports elevated
error rates, token validation failures, or latency spikes that are causing
downstream service authentication failures.

## Detection Signals
- CloudWatch alarm: `auth-service ErrorRate > 3%`
- Spike in 401/403 responses across multiple services
- Token validation latency P99 > 1s
- Session store (Redis) connection errors
- Downstream services reporting authentication failures

## Immediate Actions (First 5 Minutes)

1. **Check token validation latency**
   - CloudWatch metric: `auth-service.token.validation.duration`
   - If P99 > 500ms, check Redis session store connectivity
   - Run: `redis-cli -h <session-store-host> ping`

2. **Check recent middleware changes**
   - Review commits to `services/auth/middleware.py` and `services/auth/tokens.py`
   - Any changes to token signing, validation logic, or session handling are high risk
   - Initiate rollback if a correlated change is found

3. **Verify session store health**
   - Check Redis cluster status in ElastiCache console
   - Monitor: `CacheHits`, `CacheMisses`, `CurrConnections`
   - If Redis is unhealthy, enable stateless JWT fallback mode

4. **Enable stateless fallback**
   - Set feature flag: `AUTH_STATELESS_FALLBACK=true`
   - This bypasses Redis session store and validates JWTs directly
   - Reduces load on session store while issue is resolved

5. **Check downstream impact**
   - Identify which services are failing due to auth errors
   - Consider temporarily disabling auth middleware on non-critical endpoints

## Escalation
- Page **auth-team on-call** immediately
- Notify **security team** if token signing keys may be compromised
- Open war room in `#incidents`

## Rollback Procedure
```bash
# Roll back auth-service
aws ecs update-service \
  --cluster production \
  --service auth-service \
  --task-definition auth-service:PREVIOUS_REVISION \
  --force-new-deployment

# Monitor rollback
aws ecs wait services-stable \
  --cluster production \
  --services auth-service
```

## Verification
- Token validation success rate > 99%
- P99 latency < 200ms
- Downstream 401/403 rate returns to baseline
- Redis connection count stable

## Post-Incident
- Review token validation logic for performance regressions
- Add Redis health check to deployment smoke tests
- Consider circuit breaker pattern for session store dependency