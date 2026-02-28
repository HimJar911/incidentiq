---
runbook_id: RB-0055
title: Database Connection Pool Exhaustion
service: all
severity_scope: HIGH, MED
tags: [database, connection-pool, rds, postgres, exhaustion]
first_action_step: Check RDS connection count and identify which service is exhausting the pool.
---
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
# Database Connection Pool Exhaustion

## Overview
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
This runbook covers recovery when a service's database connection pool is
exhausted, causing request timeouts and cascading failures across dependent services.

## Detection Signals
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
- CloudWatch alarm: `DatabaseConnections > 80%` of max_connections
- Service errors: `connection pool exhausted` or `too many connections`
- RDS metric: `DatabaseConnections` near instance limit
- Application logs: `sqlalchemy.exc.TimeoutError` or equivalent
- Increased request latency with database query timeouts

## Immediate Actions (First 5 Minutes)
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->

1. **Identify the exhausting service**
   - RDS Performance Insights: check active connections by client
   - CloudWatch: `DatabaseConnections` per service
   - Look for connection leaks — connections that are open but idle

2. **Check RDS instance limits**
   ```sql
   -- Run on RDS directly
   SELECT count(*), state, wait_event_type
   FROM pg_stat_activity
   GROUP BY state, wait_event_type
   ORDER BY count DESC;
   ```

3. **Restart affected service pods (immediate relief)**
   ```bash
   # Force new deployment to reset connection pools
   aws ecs update-service \
     --cluster production \
     --service <service-name> \
     --force-new-deployment
   ```

4. **Kill idle connections if restart is not possible**
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle'
     AND state_change < NOW() - INTERVAL '5 minutes'
     AND datname = '<database-name>';
   ```

5. **Enable PgBouncer connection pooling (if not already active)**
   - Route traffic through PgBouncer proxy
   - Set feature flag: `DB_USE_PGBOUNCER=true`

## Escalation
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
- Page **database-team on-call** if connection count does not drop within 10 minutes
- Consider RDS instance upgrade if max_connections is consistently near limit

## Connection Pool Settings Reference
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
| Service | Pool Size | Max Overflow | Pool Timeout |
|---------|-----------|--------------|--------------|
| payments-service | 20 | 10 | 30s |
| auth-service | 15 | 5 | 20s |
| user-service | 25 | 10 | 30s |

## Verification
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
- `DatabaseConnections` metric drops below 60% of limit
- Service error rate returns to baseline
- No `connection pool exhausted` errors in logs
- Query latency P99 within normal range

## Post-Incident
<!-- iq:runbook_id=RB-0055 | title=Database Connection Pool Exhaustion | first_action_step=Check RDS connection count and identify which service is exhausting the pool. -->
- Review connection pool sizing for affected service
- Add connection leak detection to CI pipeline
- Consider read replica for read-heavy workloads
- Implement connection pool monitoring dashboard