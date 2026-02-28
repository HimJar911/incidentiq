"""
FastAPI backend — V2 (SaaS architecture)

New endpoints:
  POST /api/onboard              — connect a repo (registers GitHub webhook)
  DELETE /api/repos/{repo_id}   — disconnect a repo
  GET  /api/repos               — list connected repos
  POST /api/webhook/github      — receives GitHub push events (public)

Existing endpoints unchanged:
  POST /api/replay
  POST /api/resolve
  GET  /api/incidents
  GET  /api/incidents/{id}
  GET  /api/incidents/{id}/postmortem
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from backend.models.incident import (
    create_incident,
    get_incident,
    list_recent_incidents,
    resolve_incident,
)
from backend.models.repo import (
    create_repo_config,
    get_repo_config,
    get_repo_config_by_url,
    list_repos,
    delete_repo_config,
    increment_incident_count,
    parse_webhook_repo_id,
    _url_to_repo_id,
)
from backend.orchestrator.pipeline import run_incident_pipeline, run_postmortem_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared webhook secret for GitHub signature verification
# Set this as an env var — same value goes into GitHub webhook config
GITHUB_WEBHOOK_SECRET = os.environ.get(
    "GITHUB_WEBHOOK_SECRET", "incidentiq-webhook-secret"
)

app = FastAPI(
    title="IncidentIQ API",
    description="Autonomous Incident Response — connect any GitHub repo",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────


class OnboardRequest(BaseModel):
    github_url: str  # "https://github.com/org/repo"
    slack_webhook_url: str  # "https://hooks.slack.com/services/..."
    github_token: str  # PAT with repo + admin:repo_hook scopes


class ResolveRequest(BaseModel):
    incident_id: str


class ReplayRequest(BaseModel):
    payload_name: str = "payments_service_high"
    custom_payload: dict | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "service": "incidentiq-api", "version": "2.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding — connect / disconnect repos
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/onboard")
def onboard_repo(request: OnboardRequest):
    """
    Connect a GitHub repo to IncidentIQ.
    1. Validates the GitHub token has access to the repo
    2. Registers a webhook on the repo pointing to /api/webhook/github
    3. Saves repo config (URL + Slack webhook) to DynamoDB
    """
    repo_id = _url_to_repo_id(request.github_url)
    logger.info(f"[onboard] Connecting repo: {repo_id}")

    # Check if already connected
    existing = get_repo_config(repo_id)
    if existing:
        # Update Slack webhook if re-connecting
        logger.info(f"[onboard] Repo already connected — updating config")

    # Register GitHub webhook
    webhook_id = _register_github_webhook(
        repo_id=repo_id,
        github_token=request.github_token,
    )

    if webhook_id is None:
        raise HTTPException(
            status_code=400,
            detail="Failed to register GitHub webhook. Check that your token has 'repo' and 'admin:repo_hook' scopes.",
        )

    # Save to DynamoDB
    config = create_repo_config(
        github_url=request.github_url,
        slack_webhook_url=request.slack_webhook_url,
        github_webhook_id=webhook_id,
        github_token=request.github_token,
    )

    logger.info(f"[onboard] Repo connected: {repo_id} (webhook_id={webhook_id})")

    return {
        "repo_id": repo_id,
        "status": "connected",
        "webhook_id": webhook_id,
        "message": f"IncidentIQ is now watching {repo_id}. Push a commit to trigger the pipeline.",
    }


@app.delete("/api/repos/{repo_id:path}")
def disconnect_repo(repo_id: str):
    """
    Disconnect a repo — removes GitHub webhook and DynamoDB config.
    """
    config = get_repo_config(repo_id)
    if not config:
        raise HTTPException(status_code=404, detail="Repo not connected")

    # Remove GitHub webhook
    if config.get("github_webhook_id") and config.get("github_token"):
        _deregister_github_webhook(
            repo_id=repo_id,
            webhook_id=config["github_webhook_id"],
            github_token=config["github_token"],
        )

    # Remove from DynamoDB
    delete_repo_config(repo_id)

    logger.info(f"[disconnect] Repo disconnected: {repo_id}")
    return {"repo_id": repo_id, "status": "disconnected"}


@app.get("/api/repos")
def get_repos():
    """List all connected repos for the dashboard."""
    repos = list_repos()
    # Don't expose tokens to frontend
    safe_repos = [
        {k: v for k, v in r.items() if k not in ("github_token",)} for r in repos
    ]
    return {"repos": safe_repos, "count": len(safe_repos)}


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Webhook Receiver — the core trigger
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None),
):
    """
    Receives GitHub push events.
    Triggered automatically when a commit is pushed to a connected repo.

    GitHub sends: X-GitHub-Event: push
    Payload contains: repository, commits, pusher, ref, etc.
    """
    body = await request.body()

    # Verify webhook signature (security — ensures request is from GitHub)
    if not _verify_github_signature(body, x_hub_signature_256):
        logger.warning("[webhook] Invalid signature — rejecting request")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Only handle push events
    if x_github_event != "push":
        logger.info(f"[webhook] Ignoring event: {x_github_event}")
        return {"status": "ignored", "event": x_github_event}

    payload = json.loads(body)

    # Extract repo identity
    repo_id = parse_webhook_repo_id(payload)
    if not repo_id:
        logger.warning("[webhook] Could not extract repo_id from payload")
        return {"status": "ignored", "reason": "no repo_id"}

    # Look up repo config
    repo_config = get_repo_config(repo_id)
    if not repo_config:
        logger.warning(f"[webhook] Push from unregistered repo: {repo_id}")
        return {"status": "ignored", "reason": "repo not connected"}

    # Skip branch pushes that aren't main/master
    ref = payload.get("ref", "")
    if not (ref.endswith("/main") or ref.endswith("/master")):
        logger.info(f"[webhook] Ignoring push to non-default branch: {ref}")
        return {"status": "ignored", "reason": f"non-default branch: {ref}"}

    # Extract commit data from push event
    commits = payload.get("commits", [])
    if not commits:
        logger.info("[webhook] Push with no commits — ignoring")
        return {"status": "ignored", "reason": "no commits"}

    head_commit = payload.get("head_commit", commits[-1] if commits else {})
    pusher = payload.get("pusher", {})

    logger.info(
        f"[webhook] Push received: {repo_id} | "
        f"commit={head_commit.get('id', '')[:8]} | "
        f"author={pusher.get('name', 'unknown')} | "
        f"message={head_commit.get('message', '')[:60]}"
    )

    # Build alert payload — mirrors CloudWatch alarm structure for agent compatibility
    alert_payload = _build_alert_payload_from_push(
        payload=payload,
        head_commit=head_commit,
        pusher=pusher,
        repo_id=repo_id,
        commits=commits,
    )

    # Create incident
    incident_id = create_incident(
        alert_payload=alert_payload,
        alert_source="GitHub",
        repo_id=repo_id,
        slack_webhook_url=repo_config.get("slack_webhook_url"),
    )

    increment_incident_count(repo_id)
    logger.info(f"[webhook] Incident created: {incident_id} for repo {repo_id}")

    # Run pipeline in background
    background_tasks.add_task(_run_pipeline_safe, incident_id)

    return {
        "incident_id": incident_id,
        "status": "ingested",
        "repo_id": repo_id,
        "commit": head_commit.get("id", "")[:8],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Existing endpoints (unchanged)
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/replay")
def replay_incident(request: ReplayRequest, background_tasks: BackgroundTasks):
    payload = request.custom_payload or _load_replay_payload(request.payload_name)
    incident_id = create_incident(alert_payload=payload, alert_source="Replay")
    background_tasks.add_task(_run_pipeline_safe, incident_id)
    return {"incident_id": incident_id, "status": "ingested"}


@app.post("/api/resolve")
def resolve(request: ResolveRequest, background_tasks: BackgroundTasks):
    try:
        get_incident(request.incident_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Incident not found")
    resolve_incident(request.incident_id)
    background_tasks.add_task(_run_postmortem_safe, request.incident_id)
    return {"incident_id": request.incident_id, "status": "resolved"}


@app.get("/api/incidents")
def list_incidents(limit: int = 20):
    incidents = list_recent_incidents(limit=limit)
    return {"incidents": incidents, "count": len(incidents)}


@app.get("/api/incidents/{incident_id}")
def get_incident_detail(incident_id: str):
    try:
        return get_incident(incident_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Incident not found")


@app.get("/api/incidents/{incident_id}/postmortem")
def get_postmortem(incident_id: str):
    try:
        incident = get_incident(incident_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Incident not found")
    s3_path = incident.get("postmortem_s3_path")
    if not s3_path:
        raise HTTPException(status_code=404, detail="Postmortem not yet generated")
    content = _read_postmortem_from_s3(s3_path)
    return {"incident_id": incident_id, "s3_path": s3_path, "content": content}


# ─────────────────────────────────────────────────────────────────────────────
# GitHub API helpers
# ─────────────────────────────────────────────────────────────────────────────


def _register_github_webhook(repo_id: str, github_token: str) -> Optional[int]:
    """
    Register a webhook on the GitHub repo pointing to our /api/webhook/github endpoint.
    Returns webhook_id on success, None on failure.
    """
    # The public URL of our ALB — IncidentIQ webhook receiver
    alb_url = os.environ.get(
        "PUBLIC_URL", "http://incidentiq-alb-1884683334.us-east-1.elb.amazonaws.com"
    )
    webhook_url = f"{alb_url}/api/webhook/github"

    payload = json.dumps(
        {
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": GITHUB_WEBHOOK_SECRET,
                "insecure_ssl": "0",
            },
        }
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo_id}/hooks",
            data=payload,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "IncidentIQ/2.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            webhook_id = data.get("id")
            logger.info(
                f"[onboard] GitHub webhook registered: id={webhook_id} url={webhook_url}"
            )
            return webhook_id
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        logger.error(f"[onboard] GitHub webhook registration failed: {e.code} — {body}")
        return None
    except Exception as e:
        logger.error(f"[onboard] GitHub webhook registration error: {e}")
        return None


def _deregister_github_webhook(
    repo_id: str, webhook_id: int, github_token: str
) -> None:
    """Remove the webhook from GitHub."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo_id}/hooks/{webhook_id}",
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "IncidentIQ/2.0",
            },
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"[disconnect] GitHub webhook {webhook_id} removed from {repo_id}")
    except Exception as e:
        logger.warning(f"[disconnect] Could not remove webhook {webhook_id}: {e}")


def _verify_github_signature(body: bytes, signature_header: Optional[str]) -> bool:
    """
    Verify GitHub webhook HMAC-SHA256 signature.
    Ensures the request genuinely came from GitHub.
    """
    if not signature_header:
        # Allow unsigned in dev/replay mode
        if os.environ.get("VERIFY_WEBHOOK_SIGNATURE", "true").lower() == "false":
            return True
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    actual = signature_header[len("sha256=") :]
    return hmac.compare_digest(expected, actual)


def _build_alert_payload_from_push(
    payload: dict,
    head_commit: dict,
    pusher: dict,
    repo_id: str,
    commits: list[dict],
) -> dict:
    """
    Build a structured alert payload from a GitHub push event.
    Shape is compatible with what agents already expect.
    Includes commit data directly so investigation agent doesn't need to poll GitHub.
    """
    return {
        # Identity
        "source": "GitHub",
        "repo_id": repo_id,
        "repo_url": f"https://github.com/{repo_id}",
        # Push metadata
        "ref": payload.get("ref", ""),
        "before": payload.get("before", ""),
        "after": payload.get("after", ""),
        # Head commit — the one that triggered this
        "head_commit": {
            "id": head_commit.get("id", "")[:8],
            "full_sha": head_commit.get("id", ""),
            "message": head_commit.get("message", ""),
            "author": head_commit.get("author", {}).get(
                "name", pusher.get("name", "unknown")
            ),
            "author_email": head_commit.get("author", {}).get("email", ""),
            "timestamp": head_commit.get("timestamp", ""),
            "url": head_commit.get("url", ""),
            "added": head_commit.get("added", []),
            "removed": head_commit.get("removed", []),
            "modified": head_commit.get("modified", []),
        },
        # All commits in this push (for investigation agent)
        "all_commits": [
            {
                "id": c.get("id", "")[:8],
                "full_sha": c.get("id", ""),
                "message": c.get("message", ""),
                "author": c.get("author", {}).get("name", "unknown"),
                "timestamp": c.get("timestamp", ""),
                "modified": c.get("modified", []),
                "added": c.get("added", []),
                "url": c.get("url", ""),
            }
            for c in commits
        ],
        # Pusher info
        "pusher": pusher.get("name", "unknown"),
        # Alarm-compatible fields (so triage agent prompt still works)
        "AlarmName": f"github-push-{repo_id}",
        "AlarmDescription": f"Push to {repo_id} by {pusher.get('name', 'unknown')}: {head_commit.get('message', '')[:100]}",
        "NewStateValue": "ALARM",
        "NewStateReason": f"Commit {head_commit.get('id', '')[:8]}: {head_commit.get('message', '')[:100]}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline helpers
# ─────────────────────────────────────────────────────────────────────────────


def _run_pipeline_safe(incident_id: str):
    try:
        run_incident_pipeline(incident_id)
    except Exception as e:
        logger.error(f"[api] Pipeline failed for {incident_id}: {e}")


def _run_postmortem_safe(incident_id: str):
    try:
        run_postmortem_pipeline(incident_id)
    except Exception as e:
        logger.error(f"[api] Postmortem failed for {incident_id}: {e}")


def _load_replay_payload(payload_name: str) -> dict:
    import json

    replay_dir = os.path.join(os.path.dirname(__file__), "..", "..", "replay")
    payload_path = os.path.join(replay_dir, f"{payload_name}.json")
    try:
        with open(payload_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"AlarmName": "replay-fallback", "NewStateValue": "ALARM"}


def _read_postmortem_from_s3(s3_path: str) -> str:
    if s3_path.startswith("local://"):
        return "# Postmortem\n\nLocal mode."
    import boto3

    try:
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        path_parts = s3_path.replace("s3://", "").split("/", 1)
        bucket, key = path_parts[0], path_parts[1]
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        return f"# Error\n\nCould not load postmortem: {e}"
