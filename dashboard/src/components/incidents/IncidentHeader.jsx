// ─── IncidentHeader ────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { SeverityBadge, SourceBadge } from "../ui/Badge";
import { PipelineTracker } from "./PipelineTracker";

function timeAgo(iso) {
    if (!iso) return "—";
    const s = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ${m % 60}m ago`;
}

function shortId(id) {
    return id?.slice(0, 8).toUpperCase() ?? "—";
}

export function IncidentHeader({ incident, prevStatus, onResolve, onPostmortem }) {
    const isActive = !["resolved", "postmortem_ready"].includes(incident.status);
    const users = incident.estimated_users_affected ?? 0;
    // Key changes when war_room fires — triggers impactReveal animation
    const impactKey = incident.status === "war_room_posted"
        ? (incident.slack_message_id ?? "war_room")
        : "static";

    return (
        <div style={{
            background: T.bg.surface, border: `1px solid ${T.bg.border}`,
            borderRadius: 8, padding: "18px 20px",
        }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 14 }}>

                {/* Left: ID, summary, impact */}
                <div style={{ flex: 1, minWidth: 0, paddingRight: 16 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                        <span style={{ fontSize: 17, fontFamily: T.fonts.mono, fontWeight: 700, color: T.text.primary, letterSpacing: "0.04em" }}>
                            IIQ-{shortId(incident.incident_id)}
                        </span>
                        <SeverityBadge severity={incident.severity} />
                        <SourceBadge source={incident.alert_source} />
                    </div>

                    <p style={{ fontSize: 13, color: T.text.secondary, lineHeight: 1.65, margin: 0, marginBottom: users > 0 ? 12 : 0 }}>
                        {incident.triage_summary_snippet || "Awaiting triage analysis…"}
                    </p>

                    {/* Users impacted — animated reveal */}
                    {users > 0 && (
                        <div key={impactKey} style={{
                            display: "inline-flex", alignItems: "baseline", gap: 8,
                            background: T.severity.HIGH.bg, border: `1px solid ${T.severity.HIGH.border}`,
                            borderRadius: 5, padding: "6px 14px",
                            animation: "impactReveal 0.7s cubic-bezier(0.22,1,0.36,1)",
                        }}>
                            <span style={{
                                fontSize: 22, fontFamily: T.fonts.mono, fontWeight: 700,
                                color: T.severity.HIGH.fg, lineHeight: 1, letterSpacing: "-0.02em",
                                textShadow: `0 0 20px ${T.severity.HIGH.dot}44`,
                            }}>
                                {users.toLocaleString()}
                            </span>
                            <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.muted, letterSpacing: "0.1em" }}>
                                USERS IMPACTED
                            </span>
                        </div>
                    )}
                </div>

                {/* Right: Action buttons */}
                <div style={{ display: "flex", flexDirection: "column", gap: 8, flexShrink: 0 }}>
                    {incident.status === "postmortem_ready" && (
                        <button onClick={onPostmortem} style={{
                            padding: "7px 14px", fontSize: 11, fontFamily: T.fonts.mono, fontWeight: 700,
                            letterSpacing: "0.08em", borderRadius: 5,
                            border: "1px solid rgba(244,114,182,0.22)",
                            color: "#F472B6", background: "rgba(244,114,182,0.06)",
                        }}>
                            ▣ POSTMORTEM
                        </button>
                    )}
                    {isActive && (
                        <button onClick={onResolve} style={{
                            padding: "7px 14px", fontSize: 11, fontFamily: T.fonts.mono, fontWeight: 700,
                            letterSpacing: "0.08em", borderRadius: 5,
                            border: "1px solid rgba(52,211,153,0.2)",
                            color: "#34D399", background: "rgba(52,211,153,0.05)",
                        }}>
                            ✓ MARK RESOLVED
                        </button>
                    )}
                </div>
            </div>

            {/* Meta row */}
            <div style={{ display: "flex", gap: 24, fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled, marginBottom: 18 }}>
                <span>OPENED {timeAgo(incident.created_at)}</span>
                {incident.resolved_at && (
                    <span style={{ color: T.statusColors.resolved }}>RESOLVED {timeAgo(incident.resolved_at)}</span>
                )}
                <span>{incident.incident_id}</span>
            </div>

            <PipelineTracker status={incident.status} prevStatus={prevStatus} />
        </div>
    );
}