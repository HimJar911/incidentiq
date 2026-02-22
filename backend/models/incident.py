"""
Incident data model — the schema every agent reads and writes.
All agents get the incident_id and interact with DynamoDB via these helpers.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class IncidentStatus(str, Enum):
    INGESTED = "ingested"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    WAR_ROOM_POSTED = "war_room_posted"
    RESOLVED = "resolved"
    POSTMORTEM_READY = "postmortem_ready"


class Severity(str, Enum):
    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


class AlertSource(str, Enum):
    CLOUDWATCH = "CloudWatch"
    REPLAY = "Replay"
    MANUAL = "Manual"


# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB client
# ─────────────────────────────────────────────────────────────────────────────

TABLE_NAME = os.environ.get("INCIDENTS_TABLE", "incidentiq-incidents")


def _get_table():
    dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return dynamodb.Table(TABLE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _convert_floats_to_decimal(obj: Any) -> Any:
    """
    Recursively convert Python floats in a structure to Decimal objects,
    because DynamoDB (via boto3) requires Decimal for non-int numeric types.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _convert_floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_floats_to_decimal(v) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# Incident CRUD helpers
# ─────────────────────────────────────────────────────────────────────────────


def create_incident(alert_payload: dict, alert_source: str = AlertSource.CLOUDWATCH.value) -> str:
    """
    Create a new incident record. Called by the ingest Lambda.
    Returns the incident_id.
    """
    incident_id = str(uuid.uuid4())
    now = _now()

    item = {
        "incident_id": incident_id,
        "status": IncidentStatus.INGESTED.value,
        "created_at": now,
        "alert_source": alert_source,
        "alert_payload": alert_payload,         # Store inline for small payloads
        "alert_payload_s3_path": None,          # Populated for large payloads
        "severity": None,
        "blast_radius": [],
        "triage_summary_snippet": None,
        "suspect_commits": [],
        "runbook_hits": [],
        "slack_message_id": None,
        "estimated_users_affected": 0,
        "actions_log": [],
        "resolved_at": None,
        "postmortem_s3_path": None,
        "replay_blob_s3_path": None,
    }

    # Convert floats to Decimal before sending to DynamoDB
    item = _convert_floats_to_decimal(item)

    # Persist
    _get_table().put_item(Item=item)
    return incident_id


def get_incident(incident_id: str) -> dict:
    """Fetch the full incident object."""
    response = _get_table().get_item(Key={"incident_id": incident_id})
    item = response.get("Item")
    if not item:
        raise ValueError(f"Incident not found: {incident_id}")
    return item


def update_incident(incident_id: str, updates: dict) -> None:
    """
    Apply field updates to an incident.
    Use this for scalar fields (severity, status, slack_message_id, etc.)
    """
    if not updates:
        return

    # Convert any floats in update values to Decimal
    updates = _convert_floats_to_decimal(updates)

    # Build UpdateExpression dynamically
    set_expressions = []
    expression_values = {}
    expression_names = {}

    for key, value in updates.items():
        safe_key = f"#f_{key}"
        val_key = f":v_{key}"
        set_expressions.append(f"{safe_key} = {val_key}")
        expression_names[safe_key] = key
        expression_values[val_key] = value

    _get_table().update_item(
        Key={"incident_id": incident_id},
        UpdateExpression="SET " + ", ".join(set_expressions),
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
    )


def append_action_log(incident_id: str, agent: str, action_type: str, details: dict) -> None:
    """
    Append an entry to the actions_log list.
    This is the append-only audit trail that feeds the Postmortem Agent.
    """
    # Convert floats inside details to Decimal
    details = _convert_floats_to_decimal(details)

    entry = {
        "ts": _now(),
        "agent": agent,
        "action_type": action_type,
        "details": details,
    }

    _get_table().update_item(
        Key={"incident_id": incident_id},
        UpdateExpression="SET actions_log = list_append(if_not_exists(actions_log, :empty), :entry)",
        ExpressionAttributeValues={
            ":entry": [entry],
            ":empty": [],
        },
    )


def set_status(incident_id: str, status: IncidentStatus) -> None:
    """Transition incident status and log the transition."""
    update_incident(incident_id, {"status": status.value})
    append_action_log(
        incident_id,
        agent="orchestrator",
        action_type="status_transition",
        details={"new_status": status.value},
    )


def resolve_incident(incident_id: str) -> None:
    """Mark incident as resolved. Triggers Postmortem Agent."""
    now = _now()
    update_incident(incident_id, {
        "status": IncidentStatus.RESOLVED.value,
        "resolved_at": now,
    })
    append_action_log(
        incident_id,
        agent="api",
        action_type="incident_resolved",
        details={"resolved_at": now},
    )


def list_recent_incidents(limit: int = 20) -> list[dict]:
    """List recent incidents for the dashboard. Scans by created_at desc."""
    response = _get_table().scan(
        Limit=limit,
        FilterExpression="attribute_exists(created_at)",
    )
    items = response.get("Items", [])
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
