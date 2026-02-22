// ─── IncidentIQ API Layer ──────────────────────────────────────────────────────
// All fetch() calls live here. Components import from this file only.

import { ENDPOINTS } from "../config/api";

// ── Helpers ────────────────────────────────────────────────────────────────────

async function request(url, options = {}) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail ?? `Request failed: ${res.status}`);
    }
    return res.json();
}

// ── Incidents ──────────────────────────────────────────────────────────────────

/**
 * GET /api/incidents
 * Returns list of recent incidents, sorted newest first.
 */
export async function fetchIncidents(limit = 30) {
    return request(`${ENDPOINTS.incidents}?limit=${limit}`);
}

/**
 * GET /api/incidents/:id
 * Returns full incident detail including all agent outputs.
 */
export async function fetchIncident(id) {
    return request(ENDPOINTS.incident(id));
}

/**
 * GET /api/incidents/:id/postmortem
 * Returns postmortem markdown content from S3.
 */
export async function fetchPostmortem(id) {
    return request(ENDPOINTS.postmortem(id));
}

// ── Actions ────────────────────────────────────────────────────────────────────

/**
 * POST /api/replay
 * Fires a pre-recorded alarm payload. Used by the demo Replay button.
 */
export async function triggerReplay(payloadName = "payments_service_high", customPayload = null) {
    return request(ENDPOINTS.replay, {
        method: "POST",
        body: JSON.stringify({
            payload_name: payloadName,
            ...(customPayload ? { custom_payload: customPayload } : {}),
        }),
    });
}

/**
 * POST /api/resolve
 * Marks an incident as resolved and triggers postmortem pipeline.
 */
export async function resolveIncident(incidentId) {
    return request(ENDPOINTS.resolve, {
        method: "POST",
        body: JSON.stringify({ incident_id: incidentId }),
    });
}

/**
 * POST /api/ingest
 * Ingest a raw alert payload directly (for testing / Lambda bypass).
 */
export async function ingestAlert(alertPayload, alertSource = "Manual") {
    return request(ENDPOINTS.ingest, {
        method: "POST",
        body: JSON.stringify({ alert_payload: alertPayload, alert_source: alertSource }),
    });
}

/**
 * GET /health
 * Ping the backend. Used to check connectivity on mount.
 */
export async function checkHealth() {
    return request(ENDPOINTS.health);
}