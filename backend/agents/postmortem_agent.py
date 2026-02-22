"""
Postmortem Agent — Agent 5
Triggered on incident resolution. Reads the full audit trail from DynamoDB
and uses Nova 2 Lite to generate a structured postmortem markdown document.

This is the "structured long-form reasoning over distributed audit trail" 
touchpoint — call this out explicitly in the submission text.

Input:  full incident object + complete actions_log audit trail
Output: markdown postmortem → S3 + postmortem_s3_path → DynamoDB
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident
from decimal import Decimal

def _decimal_serializer(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def run_postmortem(incident_id: str) -> dict:
    """
    Main entry point for Postmortem Agent.
    Generates and uploads postmortem markdown. Returns S3 path.
    """
    logger.info(f"[postmortem_agent] Generating postmortem for {incident_id}")
    append_action_log(incident_id, "postmortem_agent", "agent_start", {})

    incident = get_incident(incident_id)

    # Generate postmortem markdown with Nova
    postmortem_md = _call_nova_postmortem(incident)

    # Upload to S3
    s3_path = _upload_to_s3(incident_id, postmortem_md)

    # Update DynamoDB
    update_incident(incident_id, {"postmortem_s3_path": s3_path})

    append_action_log(incident_id, "postmortem_agent", "postmortem_complete", {
        "s3_path": s3_path,
        "char_count": len(postmortem_md),
    })

    logger.info(f"[postmortem_agent] Postmortem complete — uploaded to {s3_path}")
    return {"postmortem_s3_path": s3_path, "postmortem_markdown": postmortem_md}


def _call_nova_postmortem(incident: dict) -> str:
    """
    Use Nova 2 Lite for structured long-form reasoning over the full audit trail.
    Returns complete postmortem markdown document.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    incident_id = incident.get("incident_id", "unknown")
    severity = incident.get("severity", "MED")
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")
    suspect_commits = incident.get("suspect_commits", [])
    runbook_hits = incident.get("runbook_hits", [])
    actions_log = incident.get("actions_log", [])
    created_at = incident.get("created_at", "")
    resolved_at = incident.get("resolved_at", "")

    # Calculate incident duration
    duration_str = _calculate_duration(created_at, resolved_at)

    # Build timeline from actions_log
    timeline_entries = _build_timeline(actions_log, created_at, resolved_at)

    system_prompt = """You are a senior SRE writing a production incident postmortem.
Write in a professional, factual, blameless tone. Focus on systems, not individuals.
Use proper Markdown formatting with headers (##), bullet points, and code blocks where appropriate.
Be thorough but concise. This document will be shared with engineering leadership.

Structure your response as a complete Markdown document with these EXACT sections:
## Summary
## Timeline  
## Root Cause
## Contributing Factors
## Impact
## Resolution
## Action Items
## Lessons Learned"""

    user_message = f"""Generate a complete blameless postmortem for this production incident.

INCIDENT DETAILS:
- Incident ID: {incident_id}
- Severity: {severity}
- Duration: {duration_str}
- Detected: {created_at}
- Resolved: {resolved_at}
- Affected Services: {', '.join(blast_radius)}
- Triage Summary: {triage_summary}

SUSPECT COMMITS (from automated investigation):
{json.dumps(suspect_commits, indent=2, default=_decimal_serializer)}

RUNBOOK SECTIONS REFERENCED:
{json.dumps([{'id': r.get('runbook_id'), 'section': r.get('section'), 'relevance': r.get('relevance')} for r in runbook_hits], indent=2, default=_decimal_serializer)}

FULL AUDIT TRAIL (chronological agent actions):
{json.dumps(timeline_entries, indent=2, default=_decimal_serializer)}

Write the complete postmortem document. 
- Summary: 2-3 sentences, what happened and impact
- Timeline: use the audit trail to reconstruct minute-by-minute
- Root Cause: identify the most likely technical root cause
- Contributing Factors: systemic issues that allowed this to happen
- Impact: quantify affected users and services
- Resolution: what was done to fix it
- Action Items: 3-5 concrete follow-up tasks with owners (use TBD for owner)
- Lessons Learned: what the team can learn from this"""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": user_message}]}],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": 2048,    # Long-form output
                "temperature": 0.4,
            },
        }),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    postmortem_text = response_body["output"]["message"]["content"][0]["text"].strip()

    # Prepend metadata header
    header = f"""# Incident Postmortem — {incident_id[:8].upper()}

> **Auto-generated by IncidentIQ** | Severity: {severity} | Duration: {duration_str}  
> *Review and edit before sharing with stakeholders*

---

"""
    return header + postmortem_text


def _upload_to_s3(incident_id: str, content: str) -> str:
    """Upload postmortem markdown to S3. Returns S3 URI."""
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    if not S3_BUCKET:
        logger.warning("[postmortem_agent] S3_BUCKET not set — skipping upload")
        return f"local://{incident_id}_postmortem.md"

    s3 = boto3.client("s3", region_name=AWS_REGION)
    key = f"postmortem-docs/{incident_id}/postmortem.md"

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/markdown",
        Metadata={"incident_id": incident_id},
    )

    return f"s3://{S3_BUCKET}/{key}"


def _calculate_duration(created_at: str, resolved_at: str) -> str:
    """Calculate human-readable incident duration."""
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
        delta = end - start
        total_minutes = int(delta.total_seconds() / 60)
        if total_minutes < 60:
            return f"{total_minutes} minutes"
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours}h {minutes}m"
    except Exception:
        return "unknown duration"


def _build_timeline(actions_log: list[dict], created_at: str, resolved_at: str) -> list[dict]:
    """Build clean timeline from actions_log for Nova context."""
    timeline = [{"ts": created_at, "event": "Incident detected — CloudWatch alarm fired"}]

    for entry in actions_log:
        agent = entry.get("agent", "")
        action_type = entry.get("action_type", "")
        ts = entry.get("ts", "")
        details = entry.get("details", {})

        # Map agent actions to human-readable timeline entries
        event_map = {
            ("triage_agent", "triage_complete"): f"Triage complete — {details.get('severity', '')} severity, blast radius: {details.get('blast_radius', [])}",
            ("investigation_agent", "investigation_complete"): f"Investigation complete — {details.get('suspect_count', 0)} suspects identified",
            ("runbook_agent", "runbook_search_complete"): f"Runbook search complete — {details.get('hits_count', 0)} relevant runbooks found",
            ("communication_agent", "slack_brief_posted"): f"War-room brief posted to Slack — ~{details.get('estimated_users_affected', 0):,} users affected",
            ("api", "incident_resolved"): "Incident marked resolved",
        }

        event_text = event_map.get((agent, action_type))
        if event_text and ts:
            timeline.append({"ts": ts, "event": event_text})

    if resolved_at:
        timeline.append({"ts": resolved_at, "event": "Incident fully resolved"})

    return sorted(timeline, key=lambda x: x.get("ts", ""))
