// ─── Dashboard Page ────────────────────────────────────────────────────────────
// Top-level page. Owns selected incident state and prevStatusMap.
// All data fetching delegated to hooks.

import { useState, useEffect, useRef } from "react";
import T from "../styles/tokens";
import { useIncidents } from "../hooks/useIncidents";
import { AppShell } from "../components/layout/AppShell";
import { IncidentDetail } from "../components/incidents/IncidentDetail";

export function Dashboard() {
    const { incidents, loading, activeCount, highCount, totalImpact } = useIncidents(30);
    const [selectedId, setSelectedId] = useState(null);
    const [prevStatusMap, setPrevStatusMap] = useState({});
    const [newIds, setNewIds] = useState(new Set());
    const prevIncidentsRef = useRef([]);

    // Auto-select first incident on load
    useEffect(() => {
        if (!selectedId && incidents.length > 0) {
            setSelectedId(incidents[0].incident_id);
        }
    }, [incidents, selectedId]);

    // Track status changes for pipeline animation
    useEffect(() => {
        const prev = prevIncidentsRef.current;
        incidents.forEach(inc => {
            const prevInc = prev.find(p => p.incident_id === inc.incident_id);
            if (prevInc && prevInc.status !== inc.status) {
                setPrevStatusMap(m => ({ ...m, [inc.incident_id]: prevInc.status }));
            }
        });
        prevIncidentsRef.current = incidents;
    }, [incidents]);

    // Track new incidents (for slide-in animation)
    useEffect(() => {
        const prev = prevIncidentsRef.current;
        const prevIds = new Set(prev.map(i => i.incident_id));
        const brandNew = incidents.filter(i => !prevIds.has(i.incident_id)).map(i => i.incident_id);
        if (brandNew.length) {
            setNewIds(ids => new Set([...ids, ...brandNew]));
            // Remove new flag after animation completes
            setTimeout(() => {
                setNewIds(ids => {
                    const next = new Set(ids);
                    brandNew.forEach(id => next.delete(id));
                    return next;
                });
            }, 2000);
        }
    }, [incidents]);

    // When replay creates a new incident, select it immediately
    const handleReplaySuccess = (incidentId) => {
        setSelectedId(incidentId);
    };

    if (loading && incidents.length === 0) {
        return (
            <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: T.bg.base, color: T.text.disabled, fontSize: 12, fontFamily: T.fonts.mono }}>
                Connecting to IncidentIQ…
            </div>
        );
    }

    return (
        <AppShell
            incidents={incidents}
            activeCount={activeCount}
            highCount={highCount}
            totalImpact={totalImpact}
            selectedId={selectedId}
            newIds={newIds}
            onSelect={setSelectedId}
            onReplaySuccess={handleReplaySuccess}
        >
            {selectedId ? (
                <IncidentDetail
                    incidentId={selectedId}
                    prevStatusMap={prevStatusMap}
                />
            ) : (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: T.text.disabled, fontSize: 13, fontFamily: T.fonts.mono }}>
                    Select an incident to view details
                </div>
            )}
        </AppShell>
    );
}