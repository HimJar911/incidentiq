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

// ─── Resolution Notes Modal ───────────────────────────────────────────────────

function ResolveModal({ onConfirm, onCancel, loading }) {
    const [notes, setNotes] = useState("");

    return (
        <div style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(0,0,0,0.7)",
            display: "flex", alignItems: "center", justifyContent: "center",
            backdropFilter: "blur(4px)",
        }}>
            <div style={{
                background: T.bg.surface,
                border: `1px solid ${T.bg.border}`,
                borderRadius: 10,
                padding: "28px 28px 24px",
                width: 480,
                maxWidth: "90vw",
                boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
            }}>
                {/* Header */}
                <div style={{ marginBottom: 20 }}>
                    <div style={{
                        fontSize: 13, fontFamily: T.fonts.mono, fontWeight: 700,
                        color: "#34D399", letterSpacing: "0.08em", marginBottom: 6,
                    }}>
                        ✓ MARK RESOLVED
                    </div>
                    <p style={{
                        fontSize: 12, color: T.text.secondary,
                        lineHeight: 1.6, margin: 0,
                    }}>
                        Describe what was done to resolve this incident. This will be included
                        in the postmortem. Push your fix commit before confirming.
                    </p>
                </div>

                {/* Notes textarea */}
                <textarea
                    autoFocus
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="e.g. Rolled back the offending commit and verified the fix in staging. Notified affected teams and confirmed service health before resolving."
                    rows={5}
                    style={{
                        width: "100%",
                        boxSizing: "border-box",
                        background: T.bg.base,
                        border: `1px solid ${T.bg.border}`,
                        borderRadius: 6,
                        padding: "10px 12px",
                        fontSize: 12,
                        fontFamily: T.fonts.mono,
                        color: T.text.primary,
                        lineHeight: 1.6,
                        resize: "vertical",
                        outline: "none",
                        marginBottom: 20,
                    }}
                    onFocus={e => {
                        e.target.style.borderColor = "rgba(52,211,153,0.4)";
                    }}
                    onBlur={e => {
                        e.target.style.borderColor = T.bg.border;
                    }}
                />

                {/* Reminder pill */}
                <div style={{
                    display: "flex", alignItems: "center", gap: 8,
                    background: "rgba(251,191,36,0.06)",
                    border: "1px solid rgba(251,191,36,0.18)",
                    borderRadius: 5, padding: "7px 12px",
                    marginBottom: 20,
                }}>
                    <span style={{ fontSize: 12 }}>⚠</span>
                    <span style={{
                        fontSize: 10, fontFamily: T.fonts.mono,
                        color: "rgba(251,191,36,0.8)", letterSpacing: "0.04em",
                    }}>
                        PUSH YOUR FIX COMMIT BEFORE CONFIRMING — the postmortem detector needs it
                    </span>
                </div>

                {/* Buttons */}
                <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                    <button
                        onClick={onCancel}
                        disabled={loading}
                        style={{
                            padding: "8px 18px", fontSize: 11, fontFamily: T.fonts.mono,
                            fontWeight: 700, letterSpacing: "0.08em", borderRadius: 5,
                            border: `1px solid ${T.bg.border}`,
                            color: T.text.secondary, background: "transparent",
                            cursor: loading ? "not-allowed" : "pointer",
                            opacity: loading ? 0.5 : 1,
                        }}
                    >
                        CANCEL
                    </button>
                    <button
                        onClick={() => onConfirm(notes)}
                        disabled={loading}
                        style={{
                            padding: "8px 18px", fontSize: 11, fontFamily: T.fonts.mono,
                            fontWeight: 700, letterSpacing: "0.08em", borderRadius: 5,
                            border: "1px solid rgba(52,211,153,0.3)",
                            color: "#34D399", background: "rgba(52,211,153,0.08)",
                            cursor: loading ? "not-allowed" : "pointer",
                            opacity: loading ? 0.7 : 1,
                            display: "flex", alignItems: "center", gap: 8,
                        }}
                    >
                        {loading && <Spinner size={10} />}
                        {loading ? "RESOLVING…" : "✓ CONFIRM RESOLVED"}
                    </button>
                </div>
            </div>
        </div>
    );
}

// ─── IncidentDetail ───────────────────────────────────────────────────────────

export function IncidentDetail({ incidentId, prevStatusMap }) {
    const { incident, loading, error } = useIncident(incidentId);
    const [showPostmortem, setShowPostmortem] = useState(false);
    const [showResolveModal, setShowResolveModal] = useState(false);
    const [resolving, setResolving] = useState(false);

    const prevStatus = prevStatusMap?.[incidentId];

    // Opens the modal — actual API call happens in handleConfirmResolve
    const handleResolve = () => {
        if (!incident || resolving) return;
        setShowResolveModal(true);
    };

    // Called when engineer clicks "Confirm Resolved" in modal
    const handleConfirmResolve = async (resolutionNotes) => {
        setResolving(true);
        try {
            await resolveIncident(incidentId, resolutionNotes);
            setShowResolveModal(false);
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

    if (error) return null;

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

            {/* Resolution notes modal */}
            {showResolveModal && (
                <ResolveModal
                    onConfirm={handleConfirmResolve}
                    onCancel={() => setShowResolveModal(false)}
                    loading={resolving}
                />
            )}

            {/* Postmortem modal — only when postmortem_ready */}
            {showPostmortem && (
                <PostmortemModal incident={incident} onClose={() => setShowPostmortem(false)} />
            )}
        </div>
    );
}