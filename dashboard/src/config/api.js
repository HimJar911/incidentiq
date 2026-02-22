// ─── API Configuration ─────────────────────────────────────────────────────────
// Change API_BASE here only. Nothing else needs to change for deployment.

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export const ENDPOINTS = {
    health: `${API_BASE}/health`,
    ingest: `${API_BASE}/api/ingest`,
    replay: `${API_BASE}/api/replay`,
    resolve: `${API_BASE}/api/resolve`,
    incidents: `${API_BASE}/api/incidents`,
    incident: (id) => `${API_BASE}/api/incidents/${id}`,
    postmortem: (id) => `${API_BASE}/api/incidents/${id}/postmortem`,
};