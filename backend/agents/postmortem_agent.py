"""
Postmortem Agent — Agent 5 (V2 — resolution notes + fix commit)

Changes from V1:
- Accepts resolution_notes from engineer (what they did to fix it)
- Accepts fix_commit (verified by fix_commit_detector, not assumed)
- Both included in postmortem document under Resolution section
- Postmortem is genuinely complete — not just agent outputs but actual human actions

Input:  full incident + resolution_notes + fix_commit
Output: markdown postmortem → S3 + postmortem_s3_path → DynamoDB
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident


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

    postmortem_md = _call_nova_postmortem(incident)
    s3_path = _upload_to_s3(incident_id, postmortem_md)

    update_incident(incident_id, {"postmortem_s3_path": s3_path})

    append_action_log(
        incident_id,
        "postmortem_agent",
        "postmortem_complete",
        {
            "s3_path": s3_path,
            "char_count": len(postmortem_md),
        },
    )

    logger.info(f"[postmortem_agent] Postmortem complete — uploaded to {s3_path}")
    return {"postmortem_s3_path": s3_path, "postmortem_markdown": postmortem_md}


def _call_nova_postmortem(incident: dict) -> str:
    """
    Use Nova 2 Lite for structured long-form reasoning over the full audit trail.
    Now includes resolution notes and verified fix commit.
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
    estimated_users = incident.get("estimated_users_affected", 0)

    # Resolution context — the human side of the story
    resolution_notes = incident.get("resolution_notes", "")
    fix_commit = incident.get("fix_commit")

    duration_str = _calculate_duration(created_at, resolved_at)
    timeline_entries = _build_timeline(actions_log, created_at, resolved_at)

    # Build resolution context section for Nova
    resolution_context = ""
    if resolution_notes:
        resolution_context += f"\nRESOLUTION NOTES FROM ENGINEER:\n{resolution_notes}\n"
    if fix_commit:
        resolution_context += f"""
VERIFIED FIX COMMIT:
  Hash: {fix_commit.get('commit_hash', '')}
  Author: {fix_commit.get('author', '')}
  Message: "{fix_commit.get('message', '')}"
  Fix description: {fix_commit.get('fix_description', '')}
  Confidence: {fix_commit.get('confidence', 0):.0%}
"""
    if not resolution_notes and not fix_commit:
        resolution_context = "\nRESOLUTION: Marked resolved manually. No fix commit detected or resolution notes provided.\n"

    system_prompt = """You are a senior SRE writing a production incident postmortem.
Write in a professional, factual, blameless tone. Focus on systems, not individuals.
Use proper Markdown formatting with headers (##), bullet points, and code blocks.
Be thorough but concise. This document will be shared with engineering leadership.

IMPORTANT: The Resolution section must accurately reflect what actually happened
based on the engineer's notes and verified fix commit. Do not invent resolution steps
that aren't supported by the provided data.

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
- Estimated Users Affected: ~{int(estimated_users):,}
- Triage Summary: {triage_summary}

SUSPECT COMMITS (automated investigation):
{json.dumps(suspect_commits, indent=2, default=_decimal_serializer)}

RUNBOOK SECTIONS REFERENCED:
{json.dumps([{'id': r.get('runbook_id'), 'section': r.get('section'), 'relevance': r.get('relevance')} for r in runbook_hits], indent=2, default=_decimal_serializer)}

FULL AUDIT TRAIL:
{json.dumps(timeline_entries, indent=2, default=_decimal_serializer)}
{resolution_context}

Write the complete postmortem.
- Resolution section: use the engineer notes and fix commit if provided. Be specific.
  If no notes/fix commit, state that resolution method was not documented.
- Action Items: 3-5 concrete follow-up tasks with owners (use TBD)
- Root Cause: cite the specific code change from suspect commits"""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps(
            {
                "messages": [{"role": "user", "content": [{"text": user_message}]}],
                "system": [{"text": system_prompt}],
                "inferenceConfig": {
                    "maxTokens": 2048,
                    "temperature": 0.4,
                },
            }
        ),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    postmortem_text = response_body["output"]["message"]["content"][0]["text"].strip()

    header = f"""# Incident Postmortem — {incident_id[:8].upper()}

> **Auto-generated by IncidentIQ** | Severity: {severity} | Duration: {duration_str}
> *Review and edit before sharing with stakeholders*

---

"""
    return header + postmortem_text


def _upload_to_s3(incident_id: str, content: str) -> str:
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    if not S3_BUCKET:
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


def _build_timeline(
    actions_log: list[dict],
    created_at: str,
    resolved_at: str,
) -> list[dict]:
    timeline = [{"ts": created_at, "event": "Incident detected — push event received"}]

    for entry in actions_log:
        agent = entry.get("agent", "")
        action_type = entry.get("action_type", "")
        ts = entry.get("ts", "")
        details = entry.get("details", {})

        event_map = {
            ("triage_agent", "triage_complete"): (
                f"Triage complete — {details.get('severity', '')} severity, "
                f"blast radius: {details.get('blast_radius', [])}"
            ),
            ("investigation_agent", "investigation_complete"): (
                f"Investigation complete — {details.get('suspect_count', 0)} suspects identified"
            ),
            ("runbook_agent", "runbook_search_complete"): (
                f"Runbook search complete — {details.get('hits_count', 0)} relevant runbooks found"
            ),
            ("communication_agent", "slack_brief_posted"): (
                f"War-room brief posted to Slack — "
                f"~{details.get('estimated_users_affected', 0):,} users affected"
            ),
            ("api", "incident_resolved"): "Incident marked resolved by engineer",
            ("api", "resolution_notes_added"): (
                f"Resolution notes recorded: {details.get('notes_preview', '')}"
            ),
            ("fix_detector", "fix_commit_identified"): (
                f"Fix commit verified: {details.get('commit_hash', '')} — "
                f"{details.get('fix_description', '')}"
            ),
        }

        event_text = event_map.get((agent, action_type))
        if event_text and ts:
            timeline.append({"ts": ts, "event": event_text})

    if resolved_at:
        timeline.append({"ts": resolved_at, "event": "Incident fully resolved"})

    return sorted(timeline, key=lambda x: x.get("ts", ""))
