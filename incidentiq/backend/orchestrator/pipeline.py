"""
Strands Agents Orchestrator — dispatches all 5 sub-agents in correct order.

Execution flow:
  1. Triage Agent           (sequential — must complete first)
  2. Investigation Agent    (parallel with Runbook Agent)
  3. Runbook Agent          (parallel with Investigation Agent)
  4. Communication Agent    (sequential — needs 1+2+3)
  5. Postmortem Agent       (triggered on resolution — separate call)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.models.incident import (
    IncidentStatus,
    append_action_log,
    get_incident,
    set_status,
)
from backend.agents.triage_agent import run_triage
from backend.agents.investigation_agent import run_investigation
from backend.agents.runbook_agent import run_runbook
from backend.agents.communication_agent import run_communication
from backend.agents.postmortem_agent import run_postmortem

logger = logging.getLogger(__name__)


def run_incident_pipeline(incident_id: str) -> None:
    """
    Main orchestration entry point.
    Called by the ingest Lambda after writing the incident to DynamoDB.
    Runs agents 1–4 synchronously (with 2+3 in parallel).
    Agent 5 (Postmortem) is triggered separately on resolution.
    """
    logger.info(f"[orchestrator] Starting pipeline for incident {incident_id}")

    try:
        # ── Step 1: Triage ────────────────────────────────────────────────────
        logger.info(f"[orchestrator] Dispatching Triage Agent")
        set_status(incident_id, IncidentStatus.TRIAGED)

        triage_result = run_triage(incident_id)
        append_action_log(incident_id, "orchestrator", "agent_complete",
                         {"agent": "triage", "result_summary": triage_result.get("triage_summary_snippet", "")})
        logger.info(f"[orchestrator] Triage complete — severity={triage_result.get('severity')}")

        # ── Step 2+3: Investigation + Runbook (parallel) ──────────────────────
        logger.info(f"[orchestrator] Dispatching Investigation + Runbook Agents in parallel")
        set_status(incident_id, IncidentStatus.INVESTIGATING)

        investigation_result = {}
        runbook_result = {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(run_investigation, incident_id): "investigation",
                executor.submit(run_runbook, incident_id): "runbook",
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    result = future.result()
                    if agent_name == "investigation":
                        investigation_result = result
                    else:
                        runbook_result = result
                    append_action_log(incident_id, "orchestrator", "agent_complete",
                                     {"agent": agent_name})
                    logger.info(f"[orchestrator] {agent_name} agent complete")
                except Exception as e:
                    logger.error(f"[orchestrator] {agent_name} agent failed: {e}")
                    append_action_log(incident_id, "orchestrator", "agent_error",
                                     {"agent": agent_name, "error": str(e)})

        # ── Step 4: Communication ─────────────────────────────────────────────
        logger.info(f"[orchestrator] Dispatching Communication Agent")
        run_communication(incident_id)
        set_status(incident_id, IncidentStatus.WAR_ROOM_POSTED)
        append_action_log(incident_id, "orchestrator", "agent_complete",
                         {"agent": "communication"})
        logger.info(f"[orchestrator] Communication agent complete — Slack brief posted")

        logger.info(f"[orchestrator] Pipeline complete for incident {incident_id}")

    except Exception as e:
        logger.error(f"[orchestrator] Pipeline failed for {incident_id}: {e}")
        append_action_log(incident_id, "orchestrator", "pipeline_error", {"error": str(e)})
        raise


def run_postmortem_pipeline(incident_id: str) -> None:
    """
    Triggered when incident is marked resolved (via API /resolve endpoint).
    Runs Postmortem Agent and transitions to postmortem_ready.
    """
    logger.info(f"[orchestrator] Starting postmortem pipeline for {incident_id}")

    try:
        run_postmortem(incident_id)
        set_status(incident_id, IncidentStatus.POSTMORTEM_READY)
        append_action_log(incident_id, "orchestrator", "agent_complete",
                         {"agent": "postmortem"})
        logger.info(f"[orchestrator] Postmortem complete for {incident_id}")

    except Exception as e:
        logger.error(f"[orchestrator] Postmortem failed for {incident_id}: {e}")
        append_action_log(incident_id, "orchestrator", "agent_error",
                         {"agent": "postmortem", "error": str(e)})
        raise
