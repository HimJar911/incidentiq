"""
Lambda Ingest Handler — triggered by SQS (which receives from SNS → CloudWatch alarm).
Parses the alarm payload and forwards to Fargate orchestrator.

Lambda's only job: parse the SQS/SNS envelope and relay to Fargate.
Fargate owns incident creation and pipeline execution.

Event flow:
  CloudWatch Alarm → SNS → SQS → this Lambda → Fargate /api/ingest
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")


def handler(event, context):
    """
    SQS event handler. Each record is one CloudWatch alarm.
    Batch size is 1 (set in CDK) so we always get exactly one record.
    """
    logger.info(f"[ingest_handler] Received {len(event.get('Records', []))} records")

    failed_items = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            # Parse SQS → SNS → CloudWatch alarm payload
            alarm_payload = _parse_record(record)
            logger.info(
                f"[ingest_handler] Parsed alarm: {alarm_payload.get('AlarmName', 'unknown')}"
            )

            # Forward to Fargate — it creates the incident and runs the full pipeline
            _trigger_orchestrator(alarm_payload)

        except Exception as e:
            logger.error(f"[ingest_handler] Failed to process record {message_id}: {e}")
            failed_items.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failed_items}


def _parse_record(record: dict) -> dict:
    """
    Parse SQS record body into a CloudWatch alarm payload dict.
    Handles two wrapping cases:
      1. SNS → SQS with raw_message_delivery=True  → body is the alarm JSON directly
      2. SNS → SQS with raw_message_delivery=False → body is SNS envelope, Message field has alarm JSON
    """
    body_str = record.get("body", "{}")

    try:
        body = json.loads(body_str)
    except json.JSONDecodeError:
        logger.warning("[ingest_handler] Body is not JSON — treating as raw string")
        return {"raw": body_str}

    # SNS envelope wrapping (raw_message_delivery=False)
    if "Message" in body and "Type" in body:
        try:
            return json.loads(body["Message"])
        except (json.JSONDecodeError, KeyError):
            return body

    # Raw delivery (raw_message_delivery=True) — body is the alarm directly
    return body


def _trigger_orchestrator(alarm_payload: dict) -> None:
    """
    POST alarm payload to Fargate /api/ingest.
    Fargate creates the incident in DynamoDB and runs the agent pipeline.
    Falls back gracefully if unreachable.
    """
    url = f"{ORCHESTRATOR_URL}/api/ingest"
    payload = json.dumps(
        {
            "alert_payload": alarm_payload,
            "alert_source": "CloudWatch",
        }
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            logger.info(
                f"[ingest_handler] Orchestrator accepted: {resp.status} — {body}"
            )
    except Exception as e:
        logger.error(f"[ingest_handler] Could not reach orchestrator: {e}")
        raise  # Re-raise so SQS retries
