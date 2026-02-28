"""
Repo model — per-repo configuration for connected GitHub repositories.
Stored in DynamoDB table: incidentiq-repos

Each record represents one connected repo with its Slack webhook and
GitHub webhook registration details.
"""

from __future__ import annotations

import os
import uuid
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
    """
    Save a connected repo config to DynamoDB.
    repo_id is derived from the GitHub URL: "owner/repo"
    Returns the full repo config dict.
    """
    # Normalize: "https://github.com/HimJar911/payments-service" → "HimJar911/payments-service"
    repo_id = _url_to_repo_id(github_url)

    item = {
        "repo_id": repo_id,
        "github_url": github_url,
        "slack_webhook_url": slack_webhook_url,
        "github_webhook_id": github_webhook_id,
        # Store token encrypted-ish — in prod this would go to Secrets Manager
        # For hackathon: store in DynamoDB (not ideal but functional)
        "github_token": github_token,
        "connected_at": _now(),
        "incident_count": 0,
        "last_incident_at": None,
    }

    _get_table().put_item(Item=item)
    return item


def get_repo_config(repo_id: str) -> Optional[dict]:
    """
    Fetch repo config by repo_id (e.g. "HimJar911/payments-service").
    Returns None if not found.
    """
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
    """Remove a repo config (on disconnect)."""
    _get_table().delete_item(Key={"repo_id": repo_id})


def increment_incident_count(repo_id: str) -> None:
    """Bump incident counter and update last_incident_at."""
    _get_table().update_item(
        Key={"repo_id": repo_id},
        UpdateExpression="SET incident_count = if_not_exists(incident_count, :zero) + :one, last_incident_at = :now",
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
    "HimJar911/payments-service" → "HimJar911/payments-service" (passthrough)
    """
    url = github_url.strip().rstrip("/")
    if "github.com/" in url:
        return url.split("github.com/")[-1]
    return url


def parse_webhook_repo_id(payload: dict) -> Optional[str]:
    """
    Extract repo_id from a GitHub webhook push payload.
    Returns "owner/repo" string or None.
    """
    repo = payload.get("repository", {})
    full_name = repo.get("full_name")
    return full_name
