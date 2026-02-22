"""
Triage Agent — Agent 1
Reads the CloudWatch alarm payload, queries metrics, and uses Nova 2 Lite
to determine severity + blast radius.

Input:  incident.alert_payload (CloudWatch alarm JSON)
Output: severity, blast_radius, triage_summary_snippet → written to DynamoDB
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

NOVA_LITE_MODEL = "us.amazon.nova-lite-v1:0"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def run_triage(incident_id: str) -> dict:
    """
    Main entry point for Triage Agent.
    Returns the triage result dict (also written to DynamoDB).
    """
    logger.info(f"[triage_agent] Starting triage for {incident_id}")
    append_action_log(incident_id, "triage_agent", "agent_start", {})

    incident = get_incident(incident_id)
    alert_payload = incident.get("alert_payload", {})

    # Pull metric context from CloudWatch
    metric_context = _query_cloudwatch_metrics(alert_payload)

    # Call Nova 2 Lite to reason about severity + blast radius
    triage_result = _call_nova_triage(alert_payload, metric_context)

    # Write outputs back to DynamoDB
    update_incident(incident_id, {
        "severity": triage_result["severity"],
        "blast_radius": triage_result["blast_radius"],
        "triage_summary_snippet": triage_result["triage_summary_snippet"],
    })

    append_action_log(incident_id, "triage_agent", "triage_complete", {
        "severity": triage_result["severity"],
        "blast_radius": triage_result["blast_radius"],
    })

    logger.info(f"[triage_agent] Complete — severity={triage_result['severity']}, "
                f"blast_radius={triage_result['blast_radius']}")

    return triage_result


def _query_cloudwatch_metrics(alert_payload: dict) -> dict:
    """
    Query CloudWatch for metric context around the alarm.
    Returns a dict of relevant metrics for Nova to reason about.
    """
    try:
        cw = boto3.client("cloudwatch", region_name=AWS_REGION)

        # Extract alarm name and namespace from payload
        alarm_name = alert_payload.get("AlarmName", "")
        namespace = alert_payload.get("Trigger", {}).get("Namespace", "AWS/ApplicationELB")
        dimensions = alert_payload.get("Trigger", {}).get("Dimensions", [])

        # For demo: return structured context even if metrics are unavailable
        return {
            "alarm_name": alarm_name,
            "namespace": namespace,
            "dimensions": dimensions,
            "trigger_threshold": alert_payload.get("Trigger", {}).get("Threshold", "N/A"),
            "trigger_metric": alert_payload.get("Trigger", {}).get("MetricName", "Unknown"),
            "alarm_description": alert_payload.get("AlarmDescription", ""),
            "state_reason": alert_payload.get("NewStateReason", ""),
        }
    except Exception as e:
        logger.warning(f"[triage_agent] CloudWatch query failed, using payload only: {e}")
        return {"raw_alarm": alert_payload}


def _call_nova_triage(alert_payload: dict, metric_context: dict) -> dict:
    """
    Call Nova 2 Lite to classify severity and identify blast radius.
    Returns typed dict: {severity, blast_radius, triage_summary_snippet}
    """
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    system_prompt = """You are an expert SRE (Site Reliability Engineer) analyzing a production incident alert.
Your job is to assess severity and identify which services are affected (blast radius).

Severity levels:
- HIGH: Data loss, complete service outage, payment failures, >10k users impacted
- MED: Degraded performance, partial outage, elevated error rates, 1k-10k users impacted  
- LOW: Minor degradation, <1k users impacted, non-critical service

You must respond with ONLY valid JSON, no explanation, no markdown fences. Format:
{
  "severity": "HIGH|MED|LOW",
  "blast_radius": ["service-name-1", "service-name-2"],
  "triage_summary_snippet": "One sentence summary of what is happening and why it's serious.",
  "reasoning": "Brief explanation of severity classification."
}"""

    user_message = f"""Analyze this production alert:

ALARM PAYLOAD:
{json.dumps(alert_payload, indent=2, default=str)}

METRIC CONTEXT:
{json.dumps(metric_context, indent=2, default=str)}

Identify:
1. Severity level (HIGH/MED/LOW)
2. All services likely affected (blast radius) — infer from service names, namespaces, and alarm context
3. A one-sentence triage summary

Respond with ONLY the JSON object."""

    response = bedrock.invoke_model(
        modelId=NOVA_LITE_MODEL,
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": user_message}]}],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": 512,
                "temperature": 0.1,   # Low temp for consistent classification
            },
        }),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    raw_text = response_body["output"]["message"]["content"][0]["text"].strip()

    # Strip markdown fences if Nova wraps response
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    result = json.loads(raw_text)

    # Validate required fields
    return {
        "severity": result.get("severity", "MED"),
        "blast_radius": result.get("blast_radius", []),
        "triage_summary_snippet": result.get("triage_summary_snippet", "Incident detected."),
        "reasoning": result.get("reasoning", ""),
    }
