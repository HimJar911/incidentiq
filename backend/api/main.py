"""
FastAPI backend — three routes are all you need:
  POST /api/ingest    — receive alarm (called by Lambda or direct)
  POST /api/replay    — inject a pre-recorded payload (for judge demo)
  POST /api/resolve   — mark incident resolved, trigger postmortem
  GET  /api/incidents — list recent incidents (dashboard polling)
  GET  /api/incidents/{id} — get single incident (dashboard detail)
"""
from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import logging
import os
from contextlib import asynccontextmanager
from threading import Thread

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.models.incident import (
    create_incident,
    get_incident,
    list_recent_incidents,
    resolve_incident,
)
from backend.orchestrator.pipeline import run_incident_pipeline, run_postmortem_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="IncidentIQ API",
    description="Autonomous Incident Response Agent — Amazon Nova AI Hackathon 2026",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response models
# ─────────────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    alert_payload: dict
    alert_source: str = "CloudWatch"


class ReplayRequest(BaseModel):
    """Inject a pre-recorded alarm payload for deterministic demo."""
    payload_name: str = "payments_service_high"
    custom_payload: dict | None = None


class ResolveRequest(BaseModel):
    incident_id: str


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "incidentiq-api"}


@app.post("/api/ingest")
def ingest_alert(request: IngestRequest, background_tasks: BackgroundTasks):
    """
    Receive a CloudWatch alarm payload.
    Creates incident in DynamoDB, then runs the full agent pipeline in background.
    """
    incident_id = create_incident(
        alert_payload=request.alert_payload,
        alert_source=request.alert_source,
    )
    logger.info(f"[api] Incident created: {incident_id}")

    # Run pipeline in background so API returns immediately
    background_tasks.add_task(_run_pipeline_safe, incident_id)

    return {
        "incident_id": incident_id,
        "status": "ingested",
        "message": "Incident created. Agent pipeline starting.",
    }


@app.post("/api/replay")
def replay_incident(request: ReplayRequest, background_tasks: BackgroundTasks):
    """
    One-click replay for judge demo.
    Injects a pre-recorded payload and runs the full pipeline.
    This is the button on the dashboard.
    """
    if request.custom_payload:
        payload = request.custom_payload
    else:
        payload = _load_replay_payload(request.payload_name)

    incident_id = create_incident(
        alert_payload=payload,
        alert_source="Replay",
    )
    logger.info(f"[api] Replay incident created: {incident_id}")

    background_tasks.add_task(_run_pipeline_safe, incident_id)

    return {
        "incident_id": incident_id,
        "status": "ingested",
        "message": f"Replay started with payload '{request.payload_name}'. Watch the dashboard.",
    }


@app.post("/api/resolve")
def resolve(request: ResolveRequest, background_tasks: BackgroundTasks):
    """
    Mark an incident as resolved. Triggers Postmortem Agent.
    Called via dashboard "Mark Resolved" button.
    """
    try:
        incident = get_incident(request.incident_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Incident not found")

    resolve_incident(request.incident_id)
    logger.info(f"[api] Incident resolved: {request.incident_id}")

    # Trigger postmortem in background
    background_tasks.add_task(_run_postmortem_safe, request.incident_id)

    return {
        "incident_id": request.incident_id,
        "status": "resolved",
        "message": "Incident resolved. Postmortem generation starting.",
    }


@app.get("/api/incidents")
def list_incidents(limit: int = 20):
    """List recent incidents for dashboard. Dashboard polls this every 2s."""
    incidents = list_recent_incidents(limit=limit)
    return {"incidents": incidents, "count": len(incidents)}


@app.get("/api/incidents/{incident_id}")
def get_incident_detail(incident_id: str):
    """Get full incident detail including all agent outputs."""
    try:
        incident = get_incident(incident_id)
        return incident
    except ValueError:
        raise HTTPException(status_code=404, detail="Incident not found")


@app.get("/api/incidents/{incident_id}/postmortem")
def get_postmortem(incident_id: str):
    """
    Return postmortem markdown content.
    Dashboard renders this inline.
    """
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
# Background task helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline_safe(incident_id: str):
    """Run the full incident pipeline, catching any errors."""
    try:
        run_incident_pipeline(incident_id)
    except Exception as e:
        logger.error(f"[api] Pipeline failed for {incident_id}: {e}")


def _run_postmortem_safe(incident_id: str):
    """Run the postmortem pipeline, catching any errors."""
    try:
        run_postmortem_pipeline(incident_id)
    except Exception as e:
        logger.error(f"[api] Postmortem pipeline failed for {incident_id}: {e}")


def _load_replay_payload(payload_name: str) -> dict:
    """Load a pre-recorded replay payload from the replay/ directory."""
    import json
    replay_dir = os.path.join(os.path.dirname(__file__), "..", "..", "replay")
    payload_path = os.path.join(replay_dir, f"{payload_name}.json")

    try:
        with open(payload_path) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"[api] Replay payload not found: {payload_name} — using default")
        return _default_replay_payload()


def _default_replay_payload() -> dict:
    """Default demo payload if no replay file found."""
    return {
        "AlarmName": "incidentiq-demo-payments-error-rate",
        "AlarmDescription": "Demo alarm: payments-service 5xx error rate spike",
        "AWSAccountId": "123456789012",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoint [8.5 (14/02/26 02:00:00)] was greater than the threshold (5.0).",
        "OldStateValue": "OK",
        "StateChangeTime": "2026-02-14T02:00:15.000+0000",
        "Region": "US East (N. Virginia)",
        "Trigger": {
            "MetricName": "ErrorRate",
            "Namespace": "IncidentIQ/Demo",
            "Dimensions": [{"name": "Service", "value": "payments-service"}],
            "Period": 60,
            "Threshold": 5.0,
            "ComparisonOperator": "GreaterThanThreshold",
        },
    }


def _read_postmortem_from_s3(s3_path: str) -> str:
    """Read postmortem markdown from S3."""
    if s3_path.startswith("local://"):
        return "# Postmortem\n\nLocal mode — S3 not configured."

    import boto3
    try:
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        # Parse s3://bucket/key
        path_parts = s3_path.replace("s3://", "").split("/", 1)
        bucket, key = path_parts[0], path_parts[1]
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.error(f"[api] Failed to read postmortem from S3: {e}")
        return f"# Error\n\nCould not load postmortem: {e}"
