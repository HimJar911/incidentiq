"""
Investigation Agent — Agent 2 (V3 — real diff analysis)

Key changes from V2:
- Fetches actual code diffs via GitHub API
- Nova sees real changed lines, not just filenames + commit messages
- Can identify specific lines, variable names, function calls that caused the incident
- Falls back to V2 behavior (filename analysis) if diff fetch fails

Input:  incident.alert_payload (contains commits for GitHub triggers)
Output: suspect_commits [{commit_hash, author, confidence, reason, diff_analysis}] → DynamoDB
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
import urllib.request

from backend.models.incident import append_action_log, get_incident, update_incident
from backend.agents.diff_fetcher import fetch_commit_diff, fetch_compare_diff

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

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
    repo_id = incident.get("repo_id", "")

    # Get GitHub token for diff fetching
    github_token = _get_github_token(incident, repo_id)

    # Get commits
    if alert_source == "GitHub" and alert_payload.get("all_commits"):
        commits = _extract_commits_from_payload(alert_payload)
        logger.info(
            f"[investigation_agent] Using {len(commits)} commits from webhook payload"
        )
    else:
        logger.info("[investigation_agent] Polling GitHub API for recent commits")
        commits = _fetch_github_commits_for_repo(incident, alert_payload)

    if not commits:
        logger.warning("[investigation_agent] No commits found — using demo fallback")
        commits = _get_demo_commits()

    # Enrich commits with real diffs
    if github_token and repo_id:
        commits = _enrich_commits_with_diffs(
            commits, repo_id, github_token, alert_payload
        )
    else:
        logger.warning(
            "[investigation_agent] No GitHub token — skipping diff enrichment"
        )

    # Ask Nova to analyze
    suspect_commits = _call_nova_investigate(
        blast_radius=blast_radius,
        triage_summary=triage_summary,
        commits=commits,
        alert_source=alert_source,
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
            "diff_enriched": any(c.get("diff") for c in commits),
        },
    )

    logger.info(f"[investigation_agent] Complete — {len(suspect_commits)} suspects")
    return {"suspect_commits": suspect_commits}


def _enrich_commits_with_diffs(
    commits: list[dict],
    repo_id: str,
    github_token: str,
    alert_payload: dict,
) -> list[dict]:
    """
    Fetch real code diffs for each commit and attach to commit dict.
    Prioritizes head commit (most likely culprit).
    Falls back gracefully if diff fetch fails.
    """
    enriched = []

    # For pushes with before/after SHAs, try compare diff first (more efficient)
    before_sha = alert_payload.get("before", "")
    after_sha = alert_payload.get("after", "")

    if before_sha and after_sha and len(commits) > 1:
        # Multi-commit push: get compare diff across the whole push
        compare_diff = fetch_compare_diff(repo_id, before_sha, after_sha, github_token)
        if compare_diff:
            logger.info(
                "[investigation_agent] Using compare diff for multi-commit push"
            )
            # Attach the compare diff to the head commit, mark others as covered
            for i, commit in enumerate(commits):
                c = dict(commit)
                if i == len(commits) - 1 or commit.get("is_head"):
                    c["diff"] = compare_diff
                    c["diff_type"] = "compare"
                else:
                    c["diff"] = None
                    c["diff_type"] = "covered_by_compare"
                enriched.append(c)
            return enriched

    # Single commit or compare failed: fetch individual diffs
    for commit in commits:
        c = dict(commit)
        sha = commit.get("full_sha") or commit.get("commit_hash", "")

        if sha and len(sha) >= 7:
            diff = fetch_commit_diff(repo_id, sha, github_token)
            c["diff"] = diff
            c["diff_type"] = "single_commit" if diff else "fetch_failed"
            if diff:
                logger.info(
                    f"[investigation_agent] Got diff for {sha[:8]}: {len(diff)} chars"
                )
        else:
            c["diff"] = None
            c["diff_type"] = "no_sha"

        enriched.append(c)

    return enriched


def _extract_commits_from_payload(alert_payload: dict) -> list[dict]:
    """Extract commit data from GitHub push webhook payload."""
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


def _call_nova_investigate(
    blast_radius: list[str],
    triage_summary: str,
    commits: list[dict],
    alert_source: str,
) -> list[dict]:
    """
    Use Nova 2 Lite to analyze commits — now with real diffs.
    Returns ranked list of suspect commits with specific reasoning.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    # Build commit analysis section
    # Separate diff content from commit metadata to keep prompt readable
    commit_summaries = []
    diff_sections = []

    for i, commit in enumerate(commits):
        summary = {
            "commit_hash": commit.get("commit_hash", ""),
            "author": commit.get("author", "unknown"),
            "message": commit.get("message", ""),
            "timestamp": commit.get("timestamp", ""),
            "files_modified": commit.get("files_modified", []),
            "files_added": commit.get("files_added", []),
            "files_removed": commit.get("files_removed", []),
            "is_head": commit.get("is_head", False),
            "has_diff": bool(commit.get("diff")),
        }
        commit_summaries.append(summary)

        if commit.get("diff"):
            diff_sections.append(
                f"=== DIFF FOR COMMIT {commit.get('commit_hash', '')[:8]} ===\n"
                f"{commit['diff']}\n"
            )

    system_prompt = """You are a senior SRE doing root cause analysis on a production incident.
You have access to the actual code diffs for recent commits.

Analyze the diffs carefully for:
- Zero/null/empty values being assigned to critical variables (divisors, rates, limits)
- Removed safety checks or validation
- Changed thresholds, timeouts, or rate limits
- Broken logic in financial calculations, auth flows, or data processing
- Missing error handling
- Dependency version changes that could break compatibility
- Config changes that could cause misconfigurations

For each suspicious commit, cite the SPECIFIC lines or variables that look dangerous.

Respond with ONLY valid JSON:
{
  "suspect_commits": [
    {
      "commit_hash": "abc12345",
      "author": "dev-name",
      "confidence": 0.95,
      "reason": "Specific explanation citing actual code: e.g. 'Sets FEE_DIVISOR = 0 on line 14, causing ZeroDivisionError in calculate_fee()'",
      "specific_issue": "The exact problematic line or pattern found in the diff"
    }
  ],
  "root_cause_hypothesis": "Specific technical hypothesis based on diff analysis."
}"""

    user_message = f"""INCIDENT CONTEXT:
Alert source: {alert_source}
Affected services: {', '.join(blast_radius)}
Triage summary: {triage_summary}

COMMIT METADATA:
{json.dumps(commit_summaries, indent=2, default=str)}

CODE DIFFS (actual changed lines):
{chr(10).join(diff_sections) if diff_sections else "No diffs available — analyze from commit metadata only."}

Rank commits by likelihood of causing this incident.
If diffs are available, cite specific lines or variables.
Confidence 0.0-1.0. Only include commits with confidence > 0.3.
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


def _get_github_token(incident: dict, repo_id: str) -> Optional[str]:
    """Get GitHub token from repo config or Secrets Manager."""
    from backend.models.repo import get_repo_config

    if repo_id:
        repo_config = get_repo_config(repo_id)
        if repo_config and repo_config.get("github_token"):
            return repo_config["github_token"]

    return _get_github_token_from_secrets()


def _fetch_github_commits_for_repo(incident: dict, alert_payload: dict) -> list[dict]:
    """Poll GitHub API for recent commits (CloudWatch/Replay fallback)."""
    from backend.models.repo import get_repo_config

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


def _get_github_token_from_secrets() -> Optional[str]:
    """Fetch GitHub token from Secrets Manager."""
    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = sm.get_secret_value(SecretId="incidentiq/github-token")
        secret = json.loads(response["SecretString"])
        return secret.get("token")
    except Exception as e:
        logger.warning(f"[investigation_agent] Could not fetch GitHub token: {e}")
        return None


def _get_demo_commits() -> list[dict]:
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


# Fix missing Optional import
from typing import Optional
