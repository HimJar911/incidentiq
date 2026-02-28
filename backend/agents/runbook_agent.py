"""
Runbook Agent — Agent 3
Performs semantic search over the Bedrock Knowledge Base and returns
the most relevant sections.

V2 changes:
- Deduplicates results by runbook_id (keeps highest relevance hit per ID)

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
KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")
MAX_RUNBOOK_RESULTS = 3


def run_runbook(incident_id: str) -> dict:
    """Main entry point. Returns runbook_hits list (also written to DynamoDB)."""
    logger.info(f"[runbook_agent] Starting runbook search for {incident_id}")
    append_action_log(incident_id, "runbook_agent", "agent_start", {})

    incident = get_incident(incident_id)
    blast_radius = incident.get("blast_radius", [])
    triage_summary = incident.get("triage_summary_snippet", "")
    severity = incident.get("severity", "MED")

    query = _build_search_query(blast_radius, triage_summary, severity)
    logger.info(f"[runbook_agent] Searching with query: {query}")

    runbook_hits = _search_knowledge_base(query)

    # ── Deduplicate by runbook_id — keep highest relevance hit per ID ─────────
    seen = {}
    for hit in runbook_hits:
        rid = hit["runbook_id"]
        if rid not in seen or hit["relevance"] > seen[rid]["relevance"]:
            seen[rid] = hit
    runbook_hits = sorted(seen.values(), key=lambda x: x["relevance"], reverse=True)
    # ─────────────────────────────────────────────────────────────────────────

    if not runbook_hits:
        logger.warning("[runbook_agent] No runbook hits — using demo fallback")
        runbook_hits = _get_demo_runbook_hits(blast_radius)

    update_incident(incident_id, {"runbook_hits": runbook_hits})

    append_action_log(
        incident_id,
        "runbook_agent",
        "runbook_search_complete",
        {
            "query": query,
            "hits_count": len(runbook_hits),
            "top_runbook": runbook_hits[0].get("runbook_id") if runbook_hits else None,
        },
    )

    logger.info(
        f"[runbook_agent] Complete — {len(runbook_hits)} runbook sections found"
    )
    return {"runbook_hits": runbook_hits}


def _build_search_query(
    blast_radius: list[str], triage_summary: str, severity: str
) -> str:
    services = " ".join(blast_radius)
    query = f"{severity} incident affecting {services}. {triage_summary}"
    return query.strip()


def _search_knowledge_base(query: str) -> list[dict]:
    if not KNOWLEDGE_BASE_ID:
        logger.warning(
            "[runbook_agent] BEDROCK_KNOWLEDGE_BASE_ID not set — skipping KB search"
        )
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
            score = result.get("score", 0.0)

            parsed = _parse_runbook_metadata(content, result)
            hits.append(
                {
                    "runbook_id": parsed["runbook_id"],
                    "section": parsed["section"],
                    "snippet": content[:500],
                    "relevance": round(float(score), 3),
                    "source_uri": result.get("location", {})
                    .get("s3Location", {})
                    .get("uri", ""),
                    "first_action_step": parsed["first_action_step"],
                }
            )

        return sorted(hits, key=lambda x: x["relevance"], reverse=True)

    except Exception as e:
        logger.error(f"[runbook_agent] Knowledge Base search failed: {e}")
        return []


def _parse_runbook_metadata(content: str, result: dict) -> dict:
    """
    Extract runbook metadata from content returned by Bedrock KB retrieval.

    Priority:
    1. Injected HTML comment: <!-- iq:runbook_id=RB-0042 | title=... | first_action_step=... -->
    2. S3 URI filename fallback
    3. H1 heading fallback
    """
    import re

    comment_match = re.search(
        r"<!--\s*iq:runbook_id=([^\s|]+)\s*\|\s*title=([^|]+?)\s*\|\s*first_action_step=(.+?)\s*-->",
        content,
        re.DOTALL,
    )
    if comment_match:
        return {
            "runbook_id": comment_match.group(1).strip(),
            "section": comment_match.group(2).strip(),
            "first_action_step": comment_match.group(3).strip(),
        }

    uri = result.get("location", {}).get("s3Location", {}).get("uri", "")
    runbook_id = "unknown"
    if uri:
        filename = uri.split("/")[-1].replace(".md", "")
        id_match = re.match(r"(RB-\d+)", filename)
        if id_match:
            runbook_id = id_match.group(1)

    section = "General"
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        section = h1_match.group(1).strip()

    return {
        "runbook_id": runbook_id,
        "section": section,
        "first_action_step": "See runbook for details.",
    }


def _get_demo_runbook_hits(blast_radius: list[str]) -> list[dict]:
    return [
        {
            "runbook_id": "RB-0042",
            "section": "Payment Gateway Timeout Recovery",
            "snippet": (
                "When payment-service reports elevated timeout errors, immediately check the "
                "gateway configuration for recent changes. Roll back any timeout/retry config "
                "changes deployed in the last 6 hours."
            ),
            "relevance": 0.94,
            "source_uri": "s3://incidentiq-runbooks/payments/gateway-timeout-recovery.md",
            "first_action_step": "Check payment gateway config for recent changes and roll back if needed.",
        },
        {
            "runbook_id": "RB-0018",
            "section": "High Error Rate — General Escalation",
            "snippet": (
                "For HIGH severity incidents with >5% error rate: (1) Page on-call lead immediately. "
                "(2) Enable enhanced logging on affected services. (3) Check recent deploys."
            ),
            "relevance": 0.78,
            "source_uri": "s3://incidentiq-runbooks/general/high-error-rate-escalation.md",
            "first_action_step": "Page on-call lead and enable enhanced logging on affected services.",
        },
    ]
