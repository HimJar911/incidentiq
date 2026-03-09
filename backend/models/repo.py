"""
Repo model V2 — per-repo configuration + analysis results.
Stored in DynamoDB table: incidentiq-repos

New fields vs V1:
  service_dependencies  — list of services this repo calls (from repo_analyzer)
  estimated_dau         — estimated daily active users (from repo_analyzer)
  tech_stack            — detected tech stack (from repo_analyzer)
  runbooks_ingested     — list of S3 keys for ingested runbooks
  analysis_completed_at — when analysis last ran
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import boto3

REPOS_TABLE = os.environ.get("REPOS_TABLE", "incidentiq-repos")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_table():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(REPOS_TABLE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────


def create_repo_config(
    github_url: str,
    slack_webhook_url: str,
    github_webhook_id: Optional[int] = None,
    github_token: Optional[str] = None,
) -> dict:
    """Save a connected repo config. Returns the full repo config dict."""
    repo_id = _url_to_repo_id(github_url)

    item = {
        "repo_id": repo_id,
        "github_url": github_url,
        "slack_webhook_url": slack_webhook_url,
        "github_webhook_id": github_webhook_id,
        "github_token": github_token,
        "connected_at": _now(),
        "incident_count": 0,
        "last_incident_at": None,
        # Analysis fields — populated by repo_analyzer after connect
        "service_dependencies": [],
        "estimated_dau": 0,
        "tech_stack": [],
        "runbooks_ingested": [],
        "analysis_completed_at": None,
        "analysis_status": "pending",  # pending | running | complete | failed
    }

    _get_table().put_item(Item=item)
    return item


def update_repo_analysis(repo_id: str, analysis_result: dict) -> None:
    """
    Store results from repo_analyzer into the repo config.
    Called after onboard analysis completes.
    """
    _get_table().update_item(
        Key={"repo_id": repo_id},
        UpdateExpression=(
            "SET service_dependencies = :deps, "
            "estimated_dau = :dau, "
            "tech_stack = :tech, "
            "runbooks_ingested = :runbooks, "
            "analysis_completed_at = :ts, "
            "analysis_status = :status"
        ),
        ExpressionAttributeValues={
            ":deps": analysis_result.get("service_dependencies", []),
            ":dau": analysis_result.get("estimated_dau", 0),
            ":tech": analysis_result.get("tech_stack", []),
            ":runbooks": analysis_result.get("runbooks_ingested", []),
            ":ts": _now(),
            ":status": "complete",
        },
    )


def set_analysis_status(repo_id: str, status: str) -> None:
    """Update analysis status (pending/running/complete/failed)."""
    _get_table().update_item(
        Key={"repo_id": repo_id},
        UpdateExpression="SET analysis_status = :status",
        ExpressionAttributeValues={":status": status},
    )


def get_repo_config(repo_id: str) -> Optional[dict]:
    """Fetch repo config by repo_id."""
    response = _get_table().get_item(Key={"repo_id": repo_id})
    return response.get("Item")


def get_repo_config_by_url(github_url: str) -> Optional[dict]:
    """Fetch repo config by GitHub URL."""
    repo_id = _url_to_repo_id(github_url)
    return get_repo_config(repo_id)


def list_repos() -> list[dict]:
    """List all connected repos."""
    response = _get_table().scan()
    items = response.get("Items", [])
    return sorted(items, key=lambda x: x.get("connected_at", ""), reverse=True)


def delete_repo_config(repo_id: str) -> None:
    """Remove a repo config."""
    _get_table().delete_item(Key={"repo_id": repo_id})


def increment_incident_count(repo_id: str) -> None:
    """Bump incident counter and update last_incident_at."""
    _get_table().update_item(
        Key={"repo_id": repo_id},
        UpdateExpression=(
            "SET incident_count = if_not_exists(incident_count, :zero) + :one, "
            "last_incident_at = :now"
        ),
        ExpressionAttributeValues={
            ":zero": 0,
            ":one": 1,
            ":now": _now(),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _url_to_repo_id(github_url: str) -> str:
    """
    Convert GitHub URL to repo_id.
    "https://github.com/HimJar911/payments-service" → "HimJar911/payments-service"
    """
    url = github_url.strip().rstrip("/")
    if "github.com/" in url:
        return url.split("github.com/")[-1]
    return url


def parse_webhook_repo_id(payload: dict) -> Optional[str]:
    """Extract repo_id from a GitHub webhook push payload."""
    repo = payload.get("repository", {})
    return repo.get("full_name")
