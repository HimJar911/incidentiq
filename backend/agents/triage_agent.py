"""
Triage Agent — Agent 1 (V2 — GitHub push trigger)

Changes from V1:
- Handles GitHub push payloads (not just CloudWatch alarms)
- Extracts commit info directly from alert_payload (no CloudWatch needed)
- Severity reasoning based on: files changed, commit message, repo context
- Still works with CloudWatch/Replay payloads as fallback

Input:  incident.alert_payload (GitHub push event OR CloudWatch alarm)
Output: severity, blast_radius, triage_summary_snippet → DynamoDB
"""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def run_triage(incident_id: str) -> dict:
    """Main entry point. Returns triage result dict."""
    logger.info(f"[triage_agent] Starting triage for {incident_id}")
    append_action_log(incident_id, "triage_agent", "agent_start", {})

    incident = get_incident(incident_id)
    alert_payload = incident.get("alert_payload", {})
    alert_source = incident.get("alert_source", "CloudWatch")

    # Build context depending on trigger source
    if alert_source == "GitHub":
        context = _build_github_context(alert_payload)
    else:
        context = _build_cloudwatch_context(alert_payload)

    # Call Nova
    triage_result = _call_nova_triage(alert_payload, context, alert_source)

    # Write to DynamoDB
    update_incident(
        incident_id,
        {
            "severity": triage_result["severity"],
            "blast_radius": triage_result["blast_radius"],
            "triage_summary_snippet": triage_result["triage_summary_snippet"],
        },
    )

    append_action_log(
        incident_id,
        "triage_agent",
        "triage_complete",
        {
            "severity": triage_result["severity"],
            "blast_radius": triage_result["blast_radius"],
        },
    )

    logger.info(
        f"[triage_agent] Complete — severity={triage_result['severity']}, "
        f"blast_radius={triage_result['blast_radius']}"
    )
    return triage_result


def _build_github_context(payload: dict) -> dict:
    """Extract structured context from a GitHub push payload."""
    head_commit = payload.get("head_commit", {})
    all_commits = payload.get("all_commits", [])

    # Aggregate all changed files across commits
    all_modified = []
    all_added = []
    all_removed = []
    for commit in all_commits:
        all_modified.extend(commit.get("modified", []))
        all_added.extend(commit.get("added", []))
        all_removed.extend(commit.get("removed", []))

    return {
        "trigger_type": "github_push",
        "repo": payload.get("repo_id", "unknown"),
        "branch": payload.get("ref", "").replace("refs/heads/", ""),
        "pusher": payload.get("pusher", "unknown"),
        "head_commit_message": head_commit.get("message", ""),
        "head_commit_sha": head_commit.get("id", ""),
        "head_commit_author": head_commit.get("author", "unknown"),
        "commit_count": len(all_commits),
        "files_modified": list(set(all_modified))[:20],
        "files_added": list(set(all_added))[:10],
        "files_removed": list(set(all_removed))[:10],
        "total_files_changed": len(set(all_modified + all_added + all_removed)),
    }


def _build_cloudwatch_context(payload: dict) -> dict:
    """Extract context from a CloudWatch alarm payload (legacy/replay support)."""
    return {
        "trigger_type": "cloudwatch_alarm",
        "alarm_name": payload.get("AlarmName", ""),
        "namespace": payload.get("Trigger", {}).get("Namespace", ""),
        "dimensions": payload.get("Trigger", {}).get("Dimensions", []),
        "threshold": payload.get("Trigger", {}).get("Threshold", "N/A"),
        "metric": payload.get("Trigger", {}).get("MetricName", "Unknown"),
        "state_reason": payload.get("NewStateReason", ""),
    }


def _call_nova_triage(alert_payload: dict, context: dict, alert_source: str) -> dict:
    """Call Nova 2 Lite to classify severity and blast radius."""
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    system_prompt = """You are an expert SRE analyzing a production incident.
Assess severity and identify affected services (blast radius).

For GitHub push triggers, assess risk based on:
- Files changed (payment/, auth/, config/, database/ = high risk)
- Commit message keywords (fix, hotfix, patch, revert, urgent = higher risk)
- Config/dependency changes (requirements.txt, package.json, *.yml = higher risk)
- Core service files vs docs/tests (service code = higher risk)

Severity levels:
- HIGH: Payment/auth service changes, config changes in critical paths, database migrations
- MED: Service code changes with moderate blast radius, dependency updates
- LOW: Tests, docs, non-critical services, frontend-only changes

Respond with ONLY valid JSON, no markdown:
{
  "severity": "HIGH|MED|LOW",
  "blast_radius": ["service-name-1", "service-name-2"],
  "triage_summary_snippet": "One sentence: what changed and why it could cause issues.",
  "reasoning": "Brief explanation of severity classification."
}"""

    user_message = f"""Analyze this production incident trigger:

SOURCE: {alert_source}

ALERT PAYLOAD:
{json.dumps(alert_payload, indent=2, default=str)}

EXTRACTED CONTEXT:
{json.dumps(context, indent=2, default=str)}

Identify severity, blast radius (which services are affected), and a one-sentence summary.
Infer service names from file paths and repo name.
Respond with ONLY the JSON object."""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps(
            {
                "messages": [{"role": "user", "content": [{"text": user_message}]}],
                "system": [{"text": system_prompt}],
                "inferenceConfig": {"maxTokens": 512, "temperature": 0.1},
            }
        ),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    raw_text = response_body["output"]["message"]["content"][0]["text"].strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    result = json.loads(raw_text)
    return {
        "severity": result.get("severity", "MED"),
        "blast_radius": result.get("blast_radius", []),
        "triage_summary_snippet": result.get(
            "triage_summary_snippet", "Incident detected."
        ),
        "reasoning": result.get("reasoning", ""),
    }
