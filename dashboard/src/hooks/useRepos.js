// dashboard/src/hooks/useRepos.js
// Fetches connected repos from /api/repos and manages onboarding form state.
// Used by the Sidebar to show connected repos + Connect form.

import { useState, useEffect, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export function useRepos() {
    const [repos, setRepos] = useState([]);
    const [showForm, setShowForm] = useState(false);
    const [loading, setLoading] = useState(true);

    const fetchRepos = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/repos`);
            const data = await res.json();
            const repoList = data.repos || [];
            setRepos(repoList);
            // Auto-show form if nothing is connected yet
            if (repoList.length === 0) setShowForm(true);
        } catch (err) {
            console.error("[useRepos] Failed to fetch repos:", err);
        } finally {
            setLoading(false);
        }
    }, []);

    // Fetch on mount
    useEffect(() => {
        fetchRepos();
    }, [fetchRepos]);

    const handleDisconnect = (repoId) => {
        setRepos((prev) => prev.filter((r) => r.repo_id !== repoId));
    };

    const handleConnectSuccess = () => {
        fetchRepos();
        setShowForm(false);
    };

    return {
        repos,
        loading,
        showForm,
        setShowForm,
        fetchRepos,
        handleDisconnect,
        handleConnectSuccess,
    };
}