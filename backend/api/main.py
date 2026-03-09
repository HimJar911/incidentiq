"""
FastAPI backend — V3

Changes from V2:
- /api/onboard triggers repo_analyzer in background after connecting
  (scrapes runbooks, builds dependency graph, estimates DAU)
- /api/webhook/github runs push_filter before creating incident
  (skips noise commits, only pages on genuinely risky pushes)
- /api/repos returns analysis_status so dashboard can show progress
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
    append_action_log,
    update_incident,
)
from backend.models.repo import (
    create_repo_config,
    get_repo_config,
    get_repo_config_by_url,
    list_repos,
    delete_repo_config,
    increment_incident_count,
    update_repo_analysis,
    set_analysis_status,
    parse_webhook_repo_id,
    _url_to_repo_id,
)
from backend.orchestrator.pipeline import run_incident_pipeline, run_postmortem_pipeline
from backend.agents.push_filter import should_run_pipeline
from backend.agents.repo_analyzer import analyze_repo
from backend.agents.fix_commit_detector import detect_fix_commit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GITHUB_WEBHOOK_SECRET = os.environ.get(
    "GITHUB_WEBHOOK_SECRET", "incidentiq-webhook-secret"
)

app = FastAPI(
    title="IncidentIQ API",
    description="Autonomous Incident Response — connect any GitHub repo",
    version="3.0.0",
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
    github_url: str
    slack_webhook_url: str
    github_token: str


class ResolveRequest(BaseModel):
    incident_id: str
    resolution_notes: Optional[str] = None  # What the engineer did to fix it


class ReplayRequest(BaseModel):
    payload_name: str = "payments_service_high"
    custom_payload: dict | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "service": "incidentiq-api", "version": "3.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/onboard")
def onboard_repo(request: OnboardRequest, background_tasks: BackgroundTasks):
    """
    Connect a GitHub repo.
    1. Register GitHub webhook
    2. Save repo config to DynamoDB
    3. Kick off repo analysis in background (runbooks, deps, DAU)
    """
    repo_id = _url_to_repo_id(request.github_url)
    logger.info(f"[onboard] Connecting repo: {repo_id}")

    existing = get_repo_config(repo_id)
    if existing:
        logger.info(f"[onboard] Repo already connected — updating config")

    webhook_id = _register_github_webhook(
        repo_id=repo_id,
        github_token=request.github_token,
    )

    if webhook_id is None:
        raise HTTPException(
            status_code=400,
            detail="Failed to register GitHub webhook. Check that your token has 'repo' and 'admin:repo_hook' scopes.",
        )

    config = create_repo_config(
        github_url=request.github_url,
        slack_webhook_url=request.slack_webhook_url,
        github_webhook_id=webhook_id,
        github_token=request.github_token,
    )

    # Kick off repo analysis in background — non-blocking
    # This populates service_dependencies, estimated_dau, runbooks
    background_tasks.add_task(
        _run_repo_analysis,
        repo_id=repo_id,
        github_token=request.github_token,
    )

    logger.info(f"[onboard] Repo connected: {repo_id} — analysis queued")

    return {
        "repo_id": repo_id,
        "status": "connected",
        "webhook_id": webhook_id,
        "analysis_status": "running",
        "message": (
            f"IncidentIQ is now watching {repo_id}. "
            f"Analyzing repo structure in background (runbooks, dependencies, scale)..."
        ),
    }


def _run_repo_analysis(repo_id: str, github_token: str) -> None:
    """
    Background task: runs full repo analysis after onboarding.
    Stores results back into DynamoDB repo config.
    """
    try:
        set_analysis_status(repo_id, "running")
        logger.info(f"[onboard] Starting repo analysis for {repo_id}")

        result = analyze_repo(repo_id=repo_id, github_token=github_token)
        update_repo_analysis(repo_id, result)

        logger.info(
            f"[onboard] Repo analysis complete for {repo_id}: "
            f"{len(result.get('runbooks_ingested', []))} runbooks, "
            f"{len(result.get('service_dependencies', []))} dependencies, "
            f"~{result.get('estimated_dau', 0):,} estimated DAU"
        )
    except Exception as e:
        logger.error(f"[onboard] Repo analysis failed for {repo_id}: {e}")
        set_analysis_status(repo_id, "failed")


@app.delete("/api/repos/{repo_id:path}")
def disconnect_repo(repo_id: str):
    """Disconnect a repo — removes GitHub webhook and DynamoDB config."""
    config = get_repo_config(repo_id)
    if not config:
        raise HTTPException(status_code=404, detail="Repo not connected")

    if config.get("github_webhook_id") and config.get("github_token"):
        _deregister_github_webhook(
            repo_id=repo_id,
            webhook_id=config["github_webhook_id"],
            github_token=config["github_token"],
        )

    delete_repo_config(repo_id)
    logger.info(f"[disconnect] Repo disconnected: {repo_id}")
    return {"repo_id": repo_id, "status": "disconnected"}


@app.get("/api/repos")
def get_repos():
    """List all connected repos. Includes analysis_status for dashboard."""
    repos = list_repos()
    safe_repos = [
        {k: v for k, v in r.items() if k not in ("github_token",)} for r in repos
    ]
    return {"repos": safe_repos, "count": len(safe_repos)}


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Webhook — main pipeline trigger
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
    Runs push_filter before creating incident — only pages on risky pushes.
    """
    body = await request.body()

    if not _verify_github_signature(body, x_hub_signature_256):
        logger.warning("[webhook] Invalid signature — rejecting request")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event != "push":
        logger.info(f"[webhook] Ignoring event: {x_github_event}")
        return {"status": "ignored", "event": x_github_event}

    payload = json.loads(body)

    repo_id = parse_webhook_repo_id(payload)
    if not repo_id:
        return {"status": "ignored", "reason": "no repo_id"}

    repo_config = get_repo_config(repo_id)
    if not repo_config:
        logger.warning(f"[webhook] Push from unregistered repo: {repo_id}")
        return {"status": "ignored", "reason": "repo not connected"}

    ref = payload.get("ref", "")
    if not (ref.endswith("/main") or ref.endswith("/master")):
        return {"status": "ignored", "reason": f"non-default branch: {ref}"}

    commits = payload.get("commits", [])
    if not commits:
        return {"status": "ignored", "reason": "no commits"}

    head_commit = payload.get("head_commit", commits[-1] if commits else {})
    pusher = payload.get("pusher", {})

    # ── Push filter — the gatekeeper ─────────────────────────────────────────
    commit_message = head_commit.get("message", "")
    all_files_changed = []
    for c in commits:
        all_files_changed.extend(c.get("modified", []))
        all_files_changed.extend(c.get("added", []))
        all_files_changed.extend(c.get("removed", []))

    should_run, filter_reason = should_run_pipeline(
        commit_message=commit_message,
        all_files_changed=all_files_changed,
        all_commits=commits,
        repo_id=repo_id,
    )

    if not should_run:
        logger.info(f"[webhook] Push filtered out: {filter_reason}")
        return {
            "status": "filtered",
            "reason": filter_reason,
            "commit": head_commit.get("id", "")[:8],
        }
    # ─────────────────────────────────────────────────────────────────────────

    logger.info(
        f"[webhook] Push passed filter — creating incident: {repo_id} | "
        f"commit={head_commit.get('id', '')[:8]} | "
        f"filter_reason='{filter_reason}'"
    )

    alert_payload = _build_alert_payload_from_push(
        payload=payload,
        head_commit=head_commit,
        pusher=pusher,
        repo_id=repo_id,
        commits=commits,
    )

    incident_id = create_incident(
        alert_payload=alert_payload,
        alert_source="GitHub",
        repo_id=repo_id,
        slack_webhook_url=repo_config.get("slack_webhook_url"),
    )

    increment_incident_count(repo_id)
    logger.info(f"[webhook] Incident created: {incident_id}")

    background_tasks.add_task(_run_pipeline_safe, incident_id)

    return {
        "incident_id": incident_id,
        "status": "ingested",
        "repo_id": repo_id,
        "commit": head_commit.get("id", "")[:8],
        "filter_reason": filter_reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Existing endpoints
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

    # Store resolution notes before resolving
    extra_fields = {}
    if request.resolution_notes:
        extra_fields["resolution_notes"] = request.resolution_notes
        append_action_log(
            request.incident_id,
            "api",
            "resolution_notes_added",
            {"notes_preview": request.resolution_notes[:120]},
        )

    resolve_incident(request.incident_id, extra_fields=extra_fields)

    # Run fix commit detection + postmortem in background
    background_tasks.add_task(_run_resolve_pipeline, request.incident_id)

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
            return data.get("id")
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
    except Exception as e:
        logger.warning(f"[disconnect] Could not remove webhook {webhook_id}: {e}")


def _verify_github_signature(body: bytes, signature_header: Optional[str]) -> bool:
    if not signature_header:
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
    return {
        "source": "GitHub",
        "repo_id": repo_id,
        "repo_url": f"https://github.com/{repo_id}",
        "ref": payload.get("ref", ""),
        "before": payload.get("before", ""),
        "after": payload.get("after", ""),
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
        "pusher": pusher.get("name", "unknown"),
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


def _run_resolve_pipeline(incident_id: str):
    """
    Runs at resolve time:
    1. Detect fix commit (verify it actually fixes the bug, not just next commit)
    2. Store fix commit in incident record
    3. Generate postmortem (now includes resolution notes + verified fix commit)
    """
    try:
        incident = get_incident(incident_id)

        # Step 1: detect fix commit
        logger.info(f"[api] Running fix commit detection for {incident_id}")
        fix_commit = detect_fix_commit(incident)

        if fix_commit:
            update_incident(incident_id, {"fix_commit": fix_commit})
            append_action_log(
                incident_id,
                "fix_detector",
                "fix_commit_identified",
                {
                    "commit_hash": fix_commit["commit_hash"],
                    "fix_description": fix_commit.get("fix_description", ""),
                    "confidence": fix_commit.get("confidence", 0),
                },
            )
            logger.info(
                f"[api] Fix commit identified: {fix_commit['commit_hash']} "
                f"({fix_commit.get('confidence', 0):.0%} confidence)"
            )
        else:
            logger.info(f"[api] No fix commit detected for {incident_id}")

        # Step 2: generate postmortem with full context
        run_postmortem_pipeline(incident_id)

    except Exception as e:
        logger.error(f"[api] Resolve pipeline failed for {incident_id}: {e}")


def _run_postmortem_safe(incident_id: str):
    try:
        run_postmortem_pipeline(incident_id)
    except Exception as e:
        logger.error(f"[api] Postmortem failed for {incident_id}: {e}")


def _load_replay_payload(payload_name: str) -> dict:
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
