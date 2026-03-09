"""
Fix Commit Detector

Runs at resolve time. Fetches commits pushed after the incident was created,
analyzes their diffs against the original bug, and identifies which commit
(if any) actually fixed the problem.

Only flags a fix commit if Nova confirms the diff reverses or addresses
the specific issue identified during investigation. Does not assume
the next commit after a bug is automatically the fix.

Input:  incident (has suspect_commits with specific_issue, repo_id, created_at)
Output: fix_commit dict or None
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import boto3

from backend.agents.diff_fetcher import fetch_commit_diff

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def detect_fix_commit(incident: dict) -> Optional[dict]:
    """
    Main entry point. Returns fix commit dict or None.

    Dict shape:
    {
        "commit_hash": "abc12345",
        "author": "dev-name",
        "message": "revert: restore TAX_RATE_MULTIPLIER to 0.08",
        "timestamp": "...",
        "confidence": 0.97,
        "fix_description": "Reverts TAX_RATE_MULTIPLIER from 0 back to 0.08,
                            directly addressing the zero-tax regulatory violation",
        "html_url": "https://github.com/..."
    }
    """
    repo_id = incident.get("repo_id", "")
    created_at = incident.get("created_at", "")
    suspect_commits = incident.get("suspect_commits", [])

    if not repo_id or not created_at:
        logger.warning("[fix_detector] Missing repo_id or created_at — skipping")
        return None

    if not suspect_commits:
        logger.warning("[fix_detector] No suspect commits — skipping fix detection")
        return None

    # Get the original bug details
    top_suspect = suspect_commits[0]
    original_issue = top_suspect.get("specific_issue") or top_suspect.get("reason", "")
    bug_commit_hash = top_suspect.get("commit_hash", "")

    if not original_issue:
        logger.warning("[fix_detector] No specific_issue in suspect commit — skipping")
        return None

    # Get GitHub token
    github_token = _get_github_token(repo_id)
    if not github_token:
        logger.warning("[fix_detector] No GitHub token — skipping fix detection")
        return None

    # Fetch commits pushed after the incident was created
    candidate_commits = _fetch_commits_since(repo_id, created_at, github_token)
    if not candidate_commits:
        logger.info("[fix_detector] No commits found after incident creation")
        return None

    # Skip the bug commit itself
    candidate_commits = [
        c
        for c in candidate_commits
        if c.get("commit_hash", "")[:8] != bug_commit_hash[:8]
    ]

    if not candidate_commits:
        logger.info("[fix_detector] No candidate fix commits found")
        return None

    logger.info(
        f"[fix_detector] Analyzing {len(candidate_commits)} candidate commits "
        f"against bug: '{original_issue[:80]}'"
    )

    # Analyze each candidate commit's diff
    for commit in candidate_commits[:5]:  # Cap at 5 candidates
        sha = commit.get("full_sha") or commit.get("commit_hash", "")
        diff = fetch_commit_diff(repo_id, sha, github_token)

        if not diff:
            continue

        result = _ask_nova_if_fix(
            original_issue=original_issue,
            bug_commit_hash=bug_commit_hash,
            candidate_commit=commit,
            candidate_diff=diff,
        )

        if result and result.get("is_fix") and result.get("confidence", 0) >= 0.75:
            logger.info(
                f"[fix_detector] Fix commit identified: {commit['commit_hash']} "
                f"confidence={result['confidence']} — {result.get('fix_description', '')}"
            )
            return {
                "commit_hash": commit["commit_hash"],
                "full_sha": commit.get("full_sha", ""),
                "author": commit.get("author", "unknown"),
                "message": commit.get("message", ""),
                "timestamp": commit.get("timestamp", ""),
                "html_url": commit.get("html_url", ""),
                "confidence": result["confidence"],
                "fix_description": result.get("fix_description", ""),
            }

    logger.info("[fix_detector] No fix commit confirmed by Nova")
    return None


def _ask_nova_if_fix(
    original_issue: str,
    bug_commit_hash: str,
    candidate_commit: dict,
    candidate_diff: str,
) -> Optional[dict]:
    """
    Ask Nova to determine if this commit fixes the original issue.
    Returns dict with is_fix, confidence, fix_description.
    """
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        system_prompt = """You are a senior engineer verifying whether a git commit fixes a known production bug.

You will be given:
1. The original bug: a specific code issue that caused a production incident
2. A candidate fix commit: its message and diff

Determine if the candidate commit actually fixes, reverts, or addresses the original bug.

Be strict — only confirm as a fix if the diff clearly reverses or corrects the specific problematic code.
A commit that adds logging, updates docs, or changes unrelated code is NOT a fix.

Respond with ONLY valid JSON:
{
    "is_fix": true/false,
    "confidence": 0.0-1.0,
    "fix_description": "One sentence explaining exactly how this commit fixes the bug, citing specific lines"
}"""

        user_message = f"""ORIGINAL BUG (commit {bug_commit_hash}):
{original_issue}

CANDIDATE FIX COMMIT:
Hash: {candidate_commit.get('commit_hash', '')}
Author: {candidate_commit.get('author', '')}
Message: "{candidate_commit.get('message', '')}"

DIFF:
{candidate_diff}

Does this commit fix the original bug? Be strict — only say yes if the diff clearly addresses it."""

        response = bedrock.invoke_model(
            modelId=NOVA_LITE_MODEL,
            body=json.dumps(
                {
                    "messages": [{"role": "user", "content": [{"text": user_message}]}],
                    "system": [{"text": system_prompt}],
                    "inferenceConfig": {"maxTokens": 256, "temperature": 0.1},
                }
            ),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        raw = response_body["output"]["message"]["content"][0]["text"].strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return json.loads(raw)

    except Exception as e:
        logger.error(f"[fix_detector] Nova analysis failed: {e}")
        return None


def _fetch_commits_since(
    repo_id: str,
    since_iso: str,
    github_token: str,
) -> list[dict]:
    """Fetch commits pushed after a given timestamp."""
    try:
        url = (
            f"https://api.github.com/repos/{repo_id}/commits"
            f"?since={since_iso}&per_page=10"
        )
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

        commits = []
        for c in data:
            commits.append(
                {
                    "commit_hash": c["sha"][:8],
                    "full_sha": c["sha"],
                    "author": c["commit"]["author"]["name"],
                    "message": c["commit"]["message"].split("\n")[0][:200],
                    "timestamp": c["commit"]["author"]["date"],
                    "html_url": c["html_url"],
                }
            )
        return commits

    except Exception as e:
        logger.error(f"[fix_detector] Failed to fetch commits since {since_iso}: {e}")
        return []


def _get_github_token(repo_id: str) -> Optional[str]:
    """Get GitHub token from repo config."""
    try:
        from backend.models.repo import get_repo_config

        config = get_repo_config(repo_id)
        if config and config.get("github_token"):
            return config["github_token"]
    except Exception:
        pass

    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = sm.get_secret_value(SecretId="incidentiq/github-token")
        secret = json.loads(response["SecretString"])
        return secret.get("token")
    except Exception as e:
        logger.warning(f"[fix_detector] Could not fetch token: {e}")
        return None
