"""
Runbook Agent — Agent 3
Performs semantic search over the Bedrock Knowledge Base (runbooks indexed
with Nova Multimodal Embeddings) and returns the most relevant sections.

Input:  incident.blast_radius, incident.triage_summary_snippet
Output: runbook_hits [{runbook_id, section, snippet, relevance}] → DynamoDB
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from backend.models.incident import append_action_log, get_incident, update_incident

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")  # Set after KB creation
MAX_RUNBOOK_RESULTS = 3


def run_runbook(incident_id: str) -> dict:
    """
    Main entry point for Runbook Agent.
    Returns runbook_hits list (also written to DynamoDB).
    """
    logger.info(f"[runbook_agent] Starting runbook search for {incident_id}")
    append_action_log(incident_id, "runbook_agent", "agent_start", {})

    incident = get_incident(incident_id)
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")
    severity = incident.get("severity", "MED")

    # Build semantic search query from incident context
    query = _build_search_query(blast_radius, triage_summary, severity)
    logger.info(f"[runbook_agent] Searching with query: {query}")

    # Search Bedrock Knowledge Base
    runbook_hits = _search_knowledge_base(query)

    if not runbook_hits:
        logger.warning("[runbook_agent] No runbook hits — using demo fallback")
        runbook_hits = _get_demo_runbook_hits(blast_radius)

    # Write to DynamoDB
    update_incident(incident_id, {"runbook_hits": runbook_hits})

    append_action_log(incident_id, "runbook_agent", "runbook_search_complete", {
        "query": query,
        "hits_count": len(runbook_hits),
        "top_runbook": runbook_hits[0].get("runbook_id") if runbook_hits else None,
    })

    logger.info(f"[runbook_agent] Complete — {len(runbook_hits)} runbook sections found")
    return {"runbook_hits": runbook_hits}


def _build_search_query(blast_radius: list[str], triage_summary: str, severity: str) -> str:
    """
    Build a rich semantic query for the Knowledge Base.
    Combine service names + triage context for best retrieval.
    """
    services = " ".join(blast_radius)
    query = f"{severity} incident affecting {services}. {triage_summary}"
    return query.strip()


def _search_knowledge_base(query: str) -> list[dict]:
    """
    Query Bedrock Knowledge Base using Nova Multimodal Embeddings.
    Returns list of runbook_hits.
    """
    if not KNOWLEDGE_BASE_ID:
        logger.warning("[runbook_agent] BEDROCK_KNOWLEDGE_BASE_ID not set — skipping KB search")
        return []

    try:
        bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)

        response = bedrock_agent.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": MAX_RUNBOOK_RESULTS,
                    "overrideSearchType": "SEMANTIC",
                }
            },
        )

        hits = []
        for result in response.get("retrievalResults", []):
            content = result.get("content", {}).get("text", "")
            metadata = result.get("metadata", {})
            score = result.get("score", 0.0)

            hits.append({
                "runbook_id": metadata.get("runbook_id", "unknown"),
                "section": metadata.get("section", "General"),
                "snippet": content[:500],  # First 500 chars
                "relevance": round(float(score), 3),
                "source_uri": result.get("location", {}).get("s3Location", {}).get("uri", ""),
                "first_action_step": metadata.get("first_action_step", "See runbook for details."),
            })

        return sorted(hits, key=lambda x: x["relevance"], reverse=True)

    except Exception as e:
        logger.error(f"[runbook_agent] Knowledge Base search failed: {e}")
        return []


def _get_demo_runbook_hits(blast_radius: list[str]) -> list[dict]:
    """
    Demo fallback runbook hits for replay mode.
    """
    primary_service = blast_radius[0] if blast_radius else "payments-service"

    return [
        {
            "runbook_id": "RB-0042",
            "section": "Payment Gateway Timeout Recovery",
            "snippet": (
                "When payment-service reports elevated timeout errors, immediately check the "
                "gateway configuration for recent changes. Roll back any timeout/retry config "
                "changes deployed in the last 6 hours. Verify downstream dependency health "
                "at /health endpoints. If timeouts exceed 30s, enable circuit breaker mode."
            ),
            "relevance": 0.94,
            "source_uri": f"s3://incidentiq-runbooks/payments/gateway-timeout-recovery.md",
            "first_action_step": "Check payment gateway config for recent changes and roll back if needed.",
        },
        {
            "runbook_id": "RB-0018",
            "section": "High Error Rate — General Escalation",
            "snippet": (
                "For HIGH severity incidents with >5% error rate: (1) Page on-call lead immediately. "
                "(2) Enable enhanced logging on affected services. (3) Check recent deploys via "
                "deploy dashboard. (4) If deploy-related, initiate rollback procedure."
            ),
            "relevance": 0.78,
            "source_uri": f"s3://incidentiq-runbooks/general/high-error-rate-escalation.md",
            "first_action_step": "Page on-call lead and enable enhanced logging on affected services.",
        },
    ]
