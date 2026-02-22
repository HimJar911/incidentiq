// ─── useIncidents ──────────────────────────────────────────────────────────────
// Polls GET /api/incidents every 2s. Returns sorted incident list + meta state.

import { useState, useEffect, useCallback, useRef } from "react";
import { fetchIncidents } from "../api/incidentApi";

const POLL_INTERVAL = 2000;

export function useIncidents(limit = 30) {
    const [incidents, setIncidents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const intervalRef = useRef(null);

    const poll = useCallback(async () => {
        try {
            const data = await fetchIncidents(limit);
            setIncidents(data.incidents ?? []);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [limit]);

    useEffect(() => {
        poll();
        intervalRef.current = setInterval(poll, POLL_INTERVAL);
        return () => clearInterval(intervalRef.current);
    }, [poll]);

    // Derived stats used by TopBar
    const activeCount = incidents.filter(
        i => !["resolved", "postmortem_ready"].includes(i.status)
    ).length;

    const highCount = incidents.filter(i => i.severity === "HIGH").length;

    const totalImpact = incidents.reduce(
        (acc, i) => acc + (i.estimated_users_affected ?? 0), 0
    );

    return { incidents, loading, error, activeCount, highCount, totalImpact };
}