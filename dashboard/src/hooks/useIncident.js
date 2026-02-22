// ─── useIncident ───────────────────────────────────────────────────────────────
// Fetches a single incident by ID.
// Polls while the incident is still active (not resolved/postmortem_ready).

import { useState, useEffect, useCallback, useRef } from "react";
import { fetchIncident } from "../api/incidentApi";

const ACTIVE_POLL = 2000;   // Poll every 2s while active
const RESOLVED_POLL = 10000;  // Poll every 10s once resolved (for postmortem_ready)

export function useIncident(incidentId) {
    const [incident, setIncident] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const intervalRef = useRef(null);

    const isTerminal = (inc) =>
        inc?.status === "postmortem_ready";

    const poll = useCallback(async () => {
        if (!incidentId) return;
        try {
            const data = await fetchIncident(incidentId);
            setIncident(data);
            setError(null);

            // Stop polling entirely once postmortem is ready
            if (isTerminal(data)) {
                clearInterval(intervalRef.current);
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [incidentId]);

    useEffect(() => {
        if (!incidentId) return;
        setLoading(true);
        setIncident(null);
        poll();

        // Start with active polling interval
        intervalRef.current = setInterval(poll, ACTIVE_POLL);

        return () => clearInterval(intervalRef.current);
    }, [incidentId, poll]);

    // Adjust poll rate once resolved
    useEffect(() => {
        if (!incident) return;
        if (incident.status === "resolved") {
            clearInterval(intervalRef.current);
            intervalRef.current = setInterval(poll, RESOLVED_POLL);
        }
    }, [incident?.status]);

    return { incident, loading, error };
}