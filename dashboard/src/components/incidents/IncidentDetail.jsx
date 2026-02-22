// ─── IncidentDetail ────────────────────────────────────────────────────────────
// Composes all agent panels for the selected incident.

import { useState } from "react";
import { useIncident } from "../../hooks/useIncident";
import { resolveIncident } from "../../api/incidentApi";
import T from "../../styles/tokens";
import { IncidentHeader } from "./IncidentHeader";
import { BlastRadius } from "../agents/BlastRadius";
import { RunbookHits } from "../agents/RunbookHits";
import { SuspectCommits } from "../agents/SuspectCommits";
import { AuditTrail } from "../agents/AuditTrail";
import { WarRoomCard } from "../agents/WarRoomCard";
import { PostmortemModal } from "../postmortem/PostmortemModal";
import { Spinner } from "../ui/Spinner";

export function IncidentDetail({ incidentId, prevStatusMap }) {
    const { incident, loading, error } = useIncident(incidentId);
    const [showPostmortem, setShowPostmortem] = useState(false);
    const [resolving, setResolving] = useState(false);

    const prevStatus = prevStatusMap?.[incidentId];

    const handleResolve = async () => {
        if (!incident || resolving) return;
        setResolving(true);
        try {
            await resolveIncident(incidentId);
        } catch (err) {
            console.error("[IncidentDetail] Resolve failed:", err);
        } finally {
            setResolving(false);
        }
    };

    if (loading) return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", gap: 10, color: T.text.disabled, fontSize: 12, fontFamily: T.fonts.mono }}>
            <Spinner size={14} /> Loading incident…
        </div>
    );

    if (error) return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: T.severity.HIGH.fg, fontSize: 12, fontFamily: T.fonts.mono }}>
            Error: {error}
        </div>
    );

    if (!incident) return null;

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 20 }}>
            {/* Header: ID, severity, summary, users impacted, pipeline */}
            <IncidentHeader
                incident={incident}
                prevStatus={prevStatus}
                onResolve={handleResolve}
                onPostmortem={() => setShowPostmortem(true)}
            />

            {/* War Room card — visible once communication_agent fires */}
            <WarRoomCard incident={incident} />

            {/* Two-col: Blast Radius + Runbook Hits */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <BlastRadius services={incident.blast_radius ?? []} />
                <RunbookHits hits={incident.runbook_hits ?? []} />
            </div>

            {/* Suspect Commits — only when populated */}
            <SuspectCommits commits={incident.suspect_commits ?? []} />

            {/* Agent Audit Trail */}
            <AuditTrail log={incident.actions_log ?? []} />

            {/* Postmortem modal — only when postmortem_ready */}
            {showPostmortem && (
                <PostmortemModal incident={incident} onClose={() => setShowPostmortem(false)} />
            )}
        </div>
    );
}