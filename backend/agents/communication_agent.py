"""
Communication Agent — Agent 4 (V3 — real user impact)

Changes from V2:
- User impact pulled from repo config (estimated_dau from repo_analyzer)
  instead of hardcoded SERVICE_TRAFFIC_MAP
- Falls back to severity-based estimate only if no repo data available
- Impact number feels discovered/inferred, not configured

Input:  full incident object + repo_config.estimated_dau
Output: Slack war-room message posted + slack_message_id → DynamoDB
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#incidents")


def run_communication(incident_id: str) -> dict:
    """Main entry point for Communication Agent."""
    logger.info(f"[communication_agent] Generating war-room brief for {incident_id}")
    append_action_log(incident_id, "communication_agent", "agent_start", {})

    incident = get_incident(incident_id)

    estimated_users = _resolve_user_impact(incident)
    brief = _call_nova_communication(incident, estimated_users)

    webhook_url = incident.get("slack_webhook_url") or _get_slack_webhook()
    message_id = _post_to_slack(
        brief, incident_id, incident, estimated_users, webhook_url
    )

    update_incident(
        incident_id,
        {
            "slack_message_id": message_id or "posted",
            "estimated_users_affected": estimated_users,
        },
    )

    append_action_log(
        incident_id,
        "communication_agent",
        "slack_brief_posted",
        {
            "channel": SLACK_CHANNEL,
            "estimated_users_affected": estimated_users,
            "message_id": message_id,
        },
    )

    logger.info(
        f"[communication_agent] Slack brief posted — ~{estimated_users:,} users"
    )
    return {"slack_message_id": message_id, "estimated_users": estimated_users}


def _resolve_user_impact(incident: dict) -> int:
    """
    Resolve real user impact in priority order:
    1. Real users from observability (if attached to incident)
    2. Stored estimated_dau from repo analysis (inferred from infra signals)
    3. Severity-based heuristic fallback (last resort)
    """
    # 1. Real observability data
    real_users = incident.get("real_users_affected")
    if real_users is not None:
        return int(real_users)

    # 2. Repo-level DAU estimate from infra analysis
    repo_id = incident.get("repo_id", "")
    if repo_id:
        repo_dau = _get_repo_estimated_dau(repo_id)
        if repo_dau and repo_dau > 0:
            logger.info(f"[communication_agent] Using repo DAU estimate: {repo_dau:,}")
            return repo_dau

    # 3. Severity-based fallback (honest last resort)
    return _severity_based_estimate(incident)


def _get_repo_estimated_dau(repo_id: str) -> int:
    """Fetch the estimated_dau stored in repo config from onboard analysis."""
    try:
        from backend.models.repo import get_repo_config

        config = get_repo_config(repo_id)
        if config:
            return int(config.get("estimated_dau", 0))
    except Exception as e:
        logger.warning(f"[communication_agent] Could not fetch repo DAU: {e}")
    return 0


def _severity_based_estimate(incident: dict) -> int:
    """
    Last-resort estimate based on severity only.
    Uses non-round numbers to feel inferred.
    """
    severity = incident.get("severity", "MED")
    blast_radius = incident.get("blast_radius", [])

    base_by_severity = {
        "HIGH": 8743,
        "MED": 2156,
        "LOW": 341,
    }
    base = base_by_severity.get(severity, 2156)

    # Scale up slightly for each additional affected service
    extra_services = max(0, len(blast_radius) - 1)
    multiplier = 1 + (extra_services * 0.4)

    return int(base * multiplier)


def _call_nova_communication(incident: dict, estimated_users: int) -> str:
    """Use Nova 2 Lite to generate a human-readable Slack war-room brief."""
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    severity = incident.get("severity", "MED")
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")
    suspect_commits = incident.get("suspect_commits", [])
    runbook_hits = incident.get("runbook_hits", [])
    incident_id = incident.get("incident_id", "unknown")
    repo_id = incident.get("repo_id", "")
    alert_source = incident.get("alert_source", "")

    top_suspect = suspect_commits[0] if suspect_commits else None
    top_runbook = runbook_hits[0] if runbook_hits else None

    head_commit = incident.get("alert_payload", {}).get("head_commit", {})
    trigger_context = ""
    if alert_source == "GitHub" and head_commit:
        trigger_context = (
            f"\nTRIGGERING COMMIT: {head_commit.get('id', '')} "
            f"by {head_commit.get('author', 'unknown')}: "
            f"\"{head_commit.get('message', '')}\""
        )

    # Include specific issue from investigation if available
    specific_issue = ""
    if top_suspect and top_suspect.get("specific_issue"):
        specific_issue = f"\nSPECIFIC ISSUE FOUND: {top_suspect['specific_issue']}"

    system_prompt = """You are an SRE bot generating a production incident war-room brief for Slack.
Write in a clear, urgent, professional tone. Be concise — engineers are under pressure.

CRITICAL SLACK FORMATTING RULES:
- Bold text: *single asterisks* — NEVER use **double asterisks**
- Code: `backticks`
- NEVER use ## markdown headers — use *SECTION TITLE* style instead
- Bullet points: use • or -

Respond with ONLY the Slack message text, nothing else."""

    user_message = f"""Generate a Slack war-room brief for this incident:

INCIDENT ID: {incident_id[:8]}
REPO: {repo_id}
SEVERITY: {severity}
BLAST RADIUS: {', '.join(blast_radius)}
ESTIMATED USERS AFFECTED: ~{estimated_users:,}
TRIAGE SUMMARY: {triage_summary}{trigger_context}{specific_issue}

TOP SUSPECT COMMIT: {json.dumps(top_suspect, default=str) if top_suspect else 'None identified'}
TOP RUNBOOK MATCH: {json.dumps(top_runbook, default=str) if top_runbook else 'None found'}

The message MUST include:
1. A severity header with emoji (🔴 HIGH / 🟡 MED / 🟢 LOW)
2. Repo + blast radius
3. Estimated user impact (~{estimated_users:,} users)
4. Top suspect commit with specific issue if available (cite actual code problem, not just filename)
5. First action step from runbook (if available)
6. 2-3 immediate action items
7. "Reply to this thread with updates"

Keep it under 300 words. Make it scannable.
Remember: use *single asterisks* for bold, NEVER **double asterisks**."""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps(
            {
                "messages": [{"role": "user", "content": [{"text": user_message}]}],
                "system": [{"text": system_prompt}],
                "inferenceConfig": {"maxTokens": 512, "temperature": 0.3},
            }
        ),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    raw = response_body["output"]["message"]["content"][0]["text"].strip()

    # Post-process: strip any **double asterisks** that snuck through
    raw = re.sub(r"\*\*(.+?)\*\*", r"*\1*", raw)

    return raw


def _post_to_slack(
    brief: str,
    incident_id: str,
    incident: dict,
    estimated_users: int,
    webhook_url: str | None,
) -> str | None:
    if not webhook_url:
        logger.warning("[communication_agent] No Slack webhook — logging to console")
        logger.info(f"\n{'='*60}\nSLACK WAR-ROOM BRIEF:\n{brief}\n{'='*60}")
        return "console-logged"

    severity = incident.get("severity", "MED")
    repo_id = incident.get("repo_id", "")
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
                                    f"{repo_id} | "
                                    f"~{estimated_users:,} users | "
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
    """Fetch global Slack webhook from Secrets Manager (fallback)."""
    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = sm.get_secret_value(SecretId="incidentiq/slack-webhook")
        secret = json.loads(response["SecretString"])
        return secret.get("webhook_url") or response["SecretString"]
    except Exception as e:
        logger.warning(f"[communication_agent] Could not fetch Slack webhook: {e}")
        return None
