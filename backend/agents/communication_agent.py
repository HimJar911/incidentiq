"""
Communication Agent — Agent 4
Aggregates outputs from Triage, Investigation, and Runbook agents and uses
Nova 2 Lite to generate a structured Slack war-room brief.

KEY REQUIREMENT: Must include estimated user impact count in the Slack message.
This is the screenshot-able moment and the LinkedIn thumbnail.

Input:  full incident object (severity, blast_radius, suspect_commits, runbook_hits)
Output: Slack war-room message posted + slack_message_id → DynamoDB
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#incidents")

# Rough traffic multiplier per service for user impact estimation
SERVICE_TRAFFIC_MAP = {
    "payments-service": 12000,
    "auth-service": 45000,
    "api-gateway": 80000,
    "user-service": 30000,
    "default": 5000,
}


def run_communication(incident_id: str) -> dict:
    """
    Main entry point for Communication Agent.
    Generates Slack brief and posts it.
    """
    logger.info(f"[communication_agent] Generating war-room brief for {incident_id}")
    append_action_log(incident_id, "communication_agent", "agent_start", {})

    incident = get_incident(incident_id)

    # Estimate user impact from blast radius
    estimated_users = _estimate_user_impact(incident.get("blast_radius", []))

    # Generate brief with Nova
    brief = _call_nova_communication(incident, estimated_users)

    # Post to Slack
    message_id = _post_to_slack(brief, incident_id, incident, estimated_users)

    # Update DynamoDB
    update_incident(incident_id, {
    "slack_message_id": message_id or "posted",
    "estimated_users_affected": estimated_users,
})

    append_action_log(incident_id, "communication_agent", "slack_brief_posted", {
        "channel": SLACK_CHANNEL,
        "estimated_users_affected": estimated_users,
        "message_id": message_id,
    })

    logger.info(f"[communication_agent] Slack brief posted — ~{estimated_users:,} users in blast radius")
    return {"slack_message_id": message_id, "estimated_users": estimated_users}


def _estimate_user_impact(blast_radius: list[str]) -> int:
    """
    Estimate affected users from blast radius services.
    Uses peak traffic map — take the highest-traffic affected service.
    """
    if not blast_radius:
        return SERVICE_TRAFFIC_MAP["default"]

    max_users = 0
    for service in blast_radius:
        # Normalize service name
        normalized = service.lower().replace(" ", "-")
        for key, traffic in SERVICE_TRAFFIC_MAP.items():
            if key in normalized or normalized in key:
                max_users = max(max_users, traffic)
                break
        else:
            max_users = max(max_users, SERVICE_TRAFFIC_MAP["default"])

    return max_users


def _call_nova_communication(incident: dict, estimated_users: int) -> str:
    """
    Use Nova 2 Lite to generate a human-readable Slack war-room brief.
    Returns formatted Slack message text.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    severity = incident.get("severity", "MED")
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")
    suspect_commits = incident.get("suspect_commits", [])
    runbook_hits = incident.get("runbook_hits", [])
    incident_id = incident.get("incident_id", "unknown")

    top_suspect = suspect_commits[0] if suspect_commits else None
    top_runbook = runbook_hits[0] if runbook_hits else None

    system_prompt = """You are an SRE bot generating a production incident war-room brief for Slack.
Write in a clear, urgent, professional tone. Be concise — engineers are under pressure.
Use Slack markdown formatting (bold with *text*, code with `code`).
NEVER use regular markdown headers (#) — use *SECTION* style instead.
Respond with ONLY the Slack message text, nothing else."""

    user_message = f"""Generate a Slack war-room brief for this incident:

INCIDENT ID: {incident_id}
SEVERITY: {severity}
BLAST RADIUS: {', '.join(blast_radius)}
ESTIMATED USERS AFFECTED: ~{estimated_users:,}
TRIAGE SUMMARY: {triage_summary}

TOP SUSPECT COMMIT: {json.dumps(top_suspect, default=str) if top_suspect else 'None identified'}
TOP RUNBOOK MATCH: {json.dumps(top_runbook, default=str) if top_runbook else 'None found'}

The message MUST include:
1. A severity header with emoji (🔴 HIGH / 🟡 MED / 🟢 LOW)
2. Blast radius (affected services)
3. Estimated user impact (use ~{estimated_users:,} users)
4. Top suspect commit with author name and PR number
5. First action step from runbook (if available)
6. 2-3 immediate action items
7. "Reply to this thread with updates"

Keep it under 300 words. Make it scannable."""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": user_message}]}],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": 512,
                "temperature": 0.3,
            },
        }),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    return response_body["output"]["message"]["content"][0]["text"].strip()


def _post_to_slack(brief: str, incident_id: str, incident: dict, estimated_users: int) -> str | None:
    """
    Post the war-room brief to Slack via webhook.
    Returns the message timestamp (used as message_id).
    """
    webhook_url = _get_slack_webhook()
    if not webhook_url:
        logger.warning("[communication_agent] No Slack webhook — logging brief to console")
        logger.info(f"\n{'='*60}\nSLACK WAR-ROOM BRIEF:\n{brief}\n{'='*60}")
        return "console-logged"

    severity = incident.get("severity", "MED")
    color_map = {"HIGH": "#ef4444", "MED": "#f59e0b", "LOW": "#10b981"}
    color = color_map.get(severity, "#6b7280")

    payload = {
        "channel": SLACK_CHANNEL,
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": brief},
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": (
                                    f"*IncidentIQ* | `{incident_id[:8]}` | "
                                    f"~{estimated_users:,} users affected | "
                                    f"Severity: *{severity}*"
                                ),
                            }
                        ],
                    },
                ],
            }
        ],
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode() or "posted"
    except Exception as e:
        logger.error(f"[communication_agent] Slack post failed: {e}")
        return None


def _get_slack_webhook() -> str | None:
    """Fetch Slack webhook URL from Secrets Manager."""
    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = sm.get_secret_value(SecretId="incidentiq/slack-webhook")
        secret = json.loads(response["SecretString"])
        return secret.get("webhook_url") or response["SecretString"]
    except Exception as e:
        logger.warning(f"[communication_agent] Could not fetch Slack webhook: {e}")
        return None
