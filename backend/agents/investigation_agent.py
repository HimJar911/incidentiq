"""
Investigation Agent — Agent 2
Queries GitHub for recent commits on affected services and uses Nova 2 Lite
to rank suspect commits by confidence.

Input:  incident.blast_radius, incident.triage_summary_snippet
Output: suspect_commits [{commit_hash, pr_number, author, confidence}] → DynamoDB
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
import urllib.request
import urllib.parse

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "your-org")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "your-repo")
LOOKBACK_HOURS = int(os.environ.get("COMMIT_LOOKBACK_HOURS", "6"))


def run_investigation(incident_id: str) -> dict:
    """
    Main entry point for Investigation Agent.
    Returns suspect_commits list (also written to DynamoDB).
    """
    logger.info(f"[investigation_agent] Starting investigation for {incident_id}")
    append_action_log(incident_id, "investigation_agent", "agent_start", {})

    incident = get_incident(incident_id)
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")

    # Fetch recent commits from GitHub
    recent_commits = _fetch_github_commits(blast_radius)

    if not recent_commits:
        logger.warning("[investigation_agent] No recent commits found — using demo fallback")
        recent_commits = _get_demo_commits()

    # Ask Nova to rank suspects
    suspect_commits = _call_nova_investigate(
        blast_radius, triage_summary, recent_commits
    )

    # Write to DynamoDB
    update_incident(incident_id, {"suspect_commits": suspect_commits})

    append_action_log(incident_id, "investigation_agent", "investigation_complete", {
        "suspect_count": len(suspect_commits),
        "top_suspect": suspect_commits[0] if suspect_commits else None,
    })

    logger.info(f"[investigation_agent] Complete — {len(suspect_commits)} suspects identified")
    return {"suspect_commits": suspect_commits}


def _fetch_github_commits(blast_radius: list[str]) -> list[dict]:
    """
    Fetch recent commits from GitHub for affected services.
    Returns list of commit metadata dicts.
    """
    github_token = _get_github_token()
    if not github_token:
        logger.warning("[investigation_agent] No GitHub token — skipping API call")
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    commits = []

    try:
        url = f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/commits?since={since}&per_page=20"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "IncidentIQ/1.0",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        for commit in data:
            commits.append({
                "commit_hash": commit["sha"][:8],
                "full_sha": commit["sha"],
                "author": commit["commit"]["author"]["name"],
                "author_email": commit["commit"]["author"]["email"],
                "message": commit["commit"]["message"][:200],
                "timestamp": commit["commit"]["author"]["date"],
                "pr_number": None,  # Would need separate API call to resolve
                "files_changed": [],  # Would need commit detail API call
                "html_url": commit["html_url"],
            })

    except Exception as e:
        logger.error(f"[investigation_agent] GitHub API error: {e}")

    return commits


def _call_nova_investigate(
    blast_radius: list[str],
    triage_summary: str,
    commits: list[dict],
) -> list[dict]:
    """
    Use Nova 2 Lite to rank commits by likelihood of causing the incident.
    Returns sorted list of suspect_commits with confidence scores.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    system_prompt = """You are a senior SRE investigating a production incident.
You will be given recent git commits and incident context. Your job is to rank which commits
most likely caused the incident.

Scoring criteria:
- Commits touching payment, auth, or core services are higher risk
- Commits with "fix", "hotfix", "patch" in message may indicate known instability
- Commits with database migrations, config changes, or dependency updates are high risk
- Recent commits (closer to incident time) score higher

Respond with ONLY valid JSON, no markdown, no explanation:
{
  "suspect_commits": [
    {
      "commit_hash": "abc12345",
      "pr_number": 1234,
      "author": "dev-name",
      "confidence": 0.92,
      "reason": "One sentence why this commit is suspect"
    }
  ],
  "root_cause_hypothesis": "One sentence hypothesis about what caused the incident."
}"""

    user_message = f"""INCIDENT CONTEXT:
Affected services (blast radius): {', '.join(blast_radius)}
Triage summary: {triage_summary}

RECENT COMMITS (last {LOOKBACK_HOURS} hours):
{json.dumps(commits, indent=2, default=str)}

Rank the commits by likelihood of causing this incident.
Include confidence 0.0-1.0 for each.
Only include commits with confidence > 0.3.
Respond with ONLY the JSON object."""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": user_message}]}],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": 1024,
                "temperature": 0.2,
            },
        }),
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


def _get_github_token() -> str | None:
    """Fetch GitHub token from Secrets Manager."""
    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = sm.get_secret_value(SecretId="incidentiq/github-token")
        secret = json.loads(response["SecretString"])
        return secret.get("token") or response["SecretString"]
    except Exception as e:
        logger.warning(f"[investigation_agent] Could not fetch GitHub token: {e}")
        return None


def _get_demo_commits() -> list[dict]:
    """
    Fallback demo commits for replay mode.
    Tells a clean story: dev-bob's payment config change is the culprit.
    """
    return [
        {
            "commit_hash": "a3f8c21d",
            "full_sha": "a3f8c21d9e4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d",
            "author": "bob.chen",
            "author_email": "bob.chen@company.com",
            "message": "feat: update payment gateway timeout config and retry logic",
            "timestamp": "2026-02-14T01:45:00Z",
            "pr_number": 2847,
            "files_changed": ["services/payments/config.py", "services/payments/gateway.py"],
            "html_url": "https://github.com/company/monorepo/commit/a3f8c21d",
        },
        {
            "commit_hash": "b9d4e77f",
            "full_sha": "b9d4e77f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d",
            "author": "alice.zhang",
            "author_email": "alice.zhang@company.com",
            "message": "docs: update API documentation for auth endpoints",
            "timestamp": "2026-02-13T22:10:00Z",
            "pr_number": 2841,
            "files_changed": ["docs/api/auth.md"],
            "html_url": "https://github.com/company/monorepo/commit/b9d4e77f",
        },
        {
            "commit_hash": "c2a1f88e",
            "full_sha": "c2a1f88e9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e",
            "author": "carlos.mendes",
            "author_email": "carlos.mendes@company.com",
            "message": "refactor: extract auth token validation to shared middleware",
            "timestamp": "2026-02-13T18:30:00Z",
            "pr_number": 2839,
            "files_changed": ["services/auth/middleware.py", "services/auth/tokens.py"],
            "html_url": "https://github.com/company/monorepo/commit/c2a1f88e",
        },
    ]
