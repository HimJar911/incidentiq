// ─── usePostmortem ─────────────────────────────────────────────────────────────
// Fetches postmortem markdown for a given incident on demand.
// Only fires when `enabled` is true (i.e. modal is open).

import { useState, useEffect } from "react";
import { fetchPostmortem } from "../api/incidentApi";

export function usePostmortem(incidentId, enabled = false) {
    const [content, setContent] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!enabled || !incidentId) return;
        setLoading(true);
        setContent(null);
        setError(null);

        fetchPostmortem(incidentId)
            .then(data => setContent(data.content))
            .catch(err => setError(err.message))
            .finally(() => setLoading(false));
    }, [incidentId, enabled]);

    return { content, loading, error };
}