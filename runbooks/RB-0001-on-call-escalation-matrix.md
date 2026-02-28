---
runbook_id: RB-0001
title: On-Call Escalation Matrix
service: all
severity_scope: HIGH, MED, LOW
tags: [escalation, on-call, pagerduty, contacts, war-room]
first_action_step: Page the on-call SRE via PagerDuty and open a war room in #incidents.
---
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->
# On-Call Escalation Matrix

## Overview
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->
This runbook defines who to contact, when, and how during a production incident.
All incidents should follow this escalation path regardless of root cause.

## Severity Definitions
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->
| Severity | Criteria | Response Time |
|----------|----------|---------------|
| HIGH | Complete outage, data loss, payment failures, >10k users | Immediate — page now |
| MED | Degraded performance, partial outage, 1k-10k users | < 5 minutes |
| LOW | Minor degradation, <1k users, non-critical service | < 30 minutes |

## Escalation Path
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->

### Immediate (0-5 minutes)
1. **Page on-call SRE** via PagerDuty — rotation: `sre-oncall`
2. **Open war room** in `#incidents` Slack channel
3. **Post initial message** with:
   - Service affected
   - Error rate / symptom
   - Time of detection
   - Severity assessment

### 5-15 Minutes (if not resolved)
4. **Page service team on-call lead**
   - payments-service → `payments-oncall`
   - auth-service → `auth-oncall`
   - platform → `platform-oncall`
5. **Start incident timeline** in war room thread

### 15+ Minutes (HIGH severity only)
6. **Page VP Engineering**
7. **Assess customer communication** — is a status page update needed?
8. **Consider rollback** if root cause is a deployment

### 30+ Minutes (HIGH severity, not resolved)
9. **Executive escalation** — CTO notification
10. **Customer communication** — status page update required
11. **All-hands war room** — pull in additional engineers

## Contact Reference
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->
| Role | PagerDuty Rotation | Slack Handle |
|------|--------------------|--------------|
| On-call SRE | sre-oncall | @oncall-sre |
| Payments Lead | payments-oncall | @payments-team |
| Auth Lead | auth-oncall | @auth-team |
| Platform Lead | platform-oncall | @platform-team |
| VP Engineering | vp-engineering | @vp-eng |

## War Room Protocol
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->
1. Pin the incident summary message in `#incidents`
2. All updates go in the thread — keep the channel clean
3. Assign roles: **Incident Commander**, **Comms Lead**, **Technical Lead**
4. Update thread every 10 minutes with status
5. Call the all-clear explicitly when resolved

## Post-Incident
<!-- iq:runbook_id=RB-0001 | title=On-Call Escalation Matrix | first_action_step=Page the on-call SRE via PagerDuty and open a war room in #incidents. -->
- File postmortem within 24 hours for HIGH severity
- File postmortem within 72 hours for MED severity
- Update this escalation matrix if contacts have changed