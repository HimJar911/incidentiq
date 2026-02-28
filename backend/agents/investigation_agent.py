"""
Investigation Agent — Agent 2 (V2 — webhook-first)

Key change from V1:
- For GitHub push triggers: commit data is already in alert_payload.
  No GitHub API polling needed. The commit that caused the incident IS
  the head_commit from the push event. We pass it directly to Nova.

- For CloudWatch/Replay triggers: falls back to GitHub API polling
  (same behavior as V1).

This is cleaner, faster, and works for any repo without needing
the repo's GitHub token at investigation time.

Input:  incident.alert_payload (contains commits for GitHub triggers)
Output: suspect_commits [{commit_hash, author, confidence, reason}] → DynamoDB
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
import urllib.request

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Fallback polling config (CloudWatch/Replay mode)
GITHUB_ORG = os.environ.get("GITHUB_ORG", "HimJar911")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "payments-service")
LOOKBACK_HOURS = int(os.environ.get("COMMIT_LOOKBACK_HOURS", "168"))


def run_investigation(incident_id: str) -> dict:
    """Main entry point. Returns suspect_commits list."""
    logger.info(f"[investigation_agent] Starting investigation for {incident_id}")
    append_action_log(incident_id, "investigation_agent", "agent_start", {})

    incident = get_incident(incident_id)
    alert_payload = incident.get("alert_payload", {})
    alert_source = incident.get("alert_source", "CloudWatch")
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")

    # Get commits — from payload (GitHub) or via API poll (CloudWatch/Replay)
    if alert_source == "GitHub" and alert_payload.get("all_commits"):
        commits = _extract_commits_from_payload(alert_payload)
        logger.info(
            f"[investigation_agent] Using {len(commits)} commits from webhook payload"
        )
    else:
        logger.info(f"[investigation_agent] Polling GitHub API for recent commits")
        commits = _fetch_github_commits_for_repo(incident, alert_payload)

    if not commits:
        logger.warning("[investigation_agent] No commits found — using demo fallback")
        commits = _get_demo_commits()

    # Ask Nova to rank suspects
    suspect_commits = _call_nova_investigate(
        blast_radius, triage_summary, commits, alert_source
    )

    update_incident(incident_id, {"suspect_commits": suspect_commits})

    append_action_log(
        incident_id,
        "investigation_agent",
        "investigation_complete",
        {
            "suspect_count": len(suspect_commits),
            "top_suspect": suspect_commits[0] if suspect_commits else None,
            "source": "webhook_payload" if alert_source == "GitHub" else "github_api",
        },
    )

    logger.info(f"[investigation_agent] Complete — {len(suspect_commits)} suspects")
    return {"suspect_commits": suspect_commits}


def _extract_commits_from_payload(alert_payload: dict) -> list[dict]:
    """
    Extract commit data directly from GitHub push webhook payload.
    This is the fast path — no API call needed.
    """
    raw_commits = alert_payload.get("all_commits", [])
    head_commit = alert_payload.get("head_commit", {})

    commits = []
    for c in raw_commits:
        commits.append(
            {
                "commit_hash": c.get("id", "")[:8],
                "full_sha": c.get("full_sha", c.get("id", "")),
                "author": c.get("author", "unknown"),
                "message": c.get("message", "")[:200],
                "timestamp": c.get("timestamp", ""),
                "files_modified": c.get("modified", []),
                "files_added": c.get("added", []),
                "files_removed": c.get("removed", []),
                "html_url": c.get("url", ""),
                "is_head": c.get("id", "")[:8] == head_commit.get("id", "")[:8],
            }
        )

    return commits


def _fetch_github_commits_for_repo(incident: dict, alert_payload: dict) -> list[dict]:
    """
    Poll GitHub API for recent commits.
    Used for CloudWatch/Replay triggers where commits aren't in the payload.
    Tries to use per-repo token from DynamoDB first, falls back to env var.
    """
    from backend.models.repo import get_repo_config

    # Try to get token from connected repo config
    repo_id = incident.get("repo_id")
    github_token = None

    if repo_id:
        repo_config = get_repo_config(repo_id)
        if repo_config:
            github_token = repo_config.get("github_token")
            org, repo = repo_id.split("/", 1)
        else:
            org, repo = GITHUB_ORG, GITHUB_REPO
    else:
        org, repo = GITHUB_ORG, GITHUB_REPO
        github_token = _get_github_token_from_secrets()

    if not github_token:
        logger.warning("[investigation_agent] No GitHub token available")
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    commits = []

    try:
        url = f"https://api.github.com/repos/{org}/{repo}/commits?since={since}&per_page=20"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "IncidentIQ/2.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        for commit in data:
            commits.append(
                {
                    "commit_hash": commit["sha"][:8],
                    "full_sha": commit["sha"],
                    "author": commit["commit"]["author"]["name"],
                    "message": commit["commit"]["message"][:200],
                    "timestamp": commit["commit"]["author"]["date"],
                    "files_modified": [],
                    "html_url": commit["html_url"],
                    "is_head": False,
                }
            )

    except Exception as e:
        logger.error(f"[investigation_agent] GitHub API error: {e}")

    return commits


def _call_nova_investigate(
    blast_radius: list[str],
    triage_summary: str,
    commits: list[dict],
    alert_source: str,
) -> list[dict]:
    """Use Nova 2 Lite to rank commits by likelihood of causing the incident."""
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    system_prompt = """You are a senior SRE investigating a production incident.
Rank git commits by likelihood of causing the incident.

Scoring criteria:
- Commits modifying payment/, auth/, config/, or core service files = high risk
- Commit messages with "fix", "hotfix", "patch", "adjust", "update config" = higher risk
- Config changes (divisor, threshold, timeout, rate) = very high risk for calculation errors
- The HEAD commit (most recent push) scores higher if it's in a risky category
- Files with zero-value or boundary-value changes (like divisor=0) are critical

Respond with ONLY valid JSON:
{
  "suspect_commits": [
    {
      "commit_hash": "abc12345",
      "author": "dev-name",
      "confidence": 0.92,
      "reason": "One sentence why this commit is suspect"
    }
  ],
  "root_cause_hypothesis": "One sentence hypothesis."
}"""

    user_message = f"""INCIDENT CONTEXT:
Alert source: {alert_source}
Affected services (blast radius): {', '.join(blast_radius)}
Triage summary: {triage_summary}

COMMITS TO ANALYZE:
{json.dumps(commits, indent=2, default=str)}

Rank by likelihood of causing this incident.
Confidence 0.0-1.0. Only include commits with confidence > 0.3.
The HEAD commit (is_head=true) is the one just pushed — weight it accordingly.
Respond with ONLY the JSON object."""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps(
            {
                "messages": [{"role": "user", "content": [{"text": user_message}]}],
                "system": [{"text": system_prompt}],
                "inferenceConfig": {"maxTokens": 1024, "temperature": 0.2},
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
    return result.get("suspect_commits", [])


def _get_github_token_from_secrets() -> str | None:
    """Fetch GitHub token from Secrets Manager (legacy fallback)."""
    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = sm.get_secret_value(SecretId="incidentiq/github-token")
        secret = json.loads(response["SecretString"])
        return secret.get("token")
    except Exception as e:
        logger.warning(f"[investigation_agent] Could not fetch GitHub token: {e}")
        return None


def _get_demo_commits() -> list[dict]:
    """Fallback demo commits."""
    return [
        {
            "commit_hash": "492110ac",
            "full_sha": "492110ac0000000000000000000000000000000000",
            "author": "him.jar",
            "message": "fix: adjust fee calculation divisor for new pricing model",
            "timestamp": "2026-02-14T01:45:00Z",
            "files_modified": ["main.py"],
            "html_url": "https://github.com/HimJar911/payments-service/commit/492110ac",
            "is_head": True,
        },
    ]
