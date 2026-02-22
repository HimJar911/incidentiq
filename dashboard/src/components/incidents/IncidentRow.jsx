// ─── IncidentRow ───────────────────────────────────────────────────────────────

import { useState } from "react";
import T from "../../styles/tokens";
import { SeverityBadge, StatusPill } from "../ui/Badge";

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

export function IncidentRow({ incident, selected, isNew, onClick }) {
    const [hovered, setHovered] = useState(false);
    const sev = T.severity[incident.severity] ?? {};
    const isLive = !incident.resolved_at;

    return (
        <div
            onClick={onClick}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            style={{
                padding: "12px 16px", cursor: "pointer",
                borderBottom: `1px solid ${T.bg.borderSubtle}`,
                borderLeft: `2px solid ${selected ? (sev.dot ?? T.accent.primary) : "transparent"}`,
                background: selected ? T.bg.raised : hovered ? T.bg.overlay + "55" : "transparent",
                transition: "background 0.12s ease, border-left-color 0.12s ease",
                animation: isNew ? "slideInLeft 0.35s ease" : "none",
            }}
        >
            {/* ID + Severity */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 5 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{
                        width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                        background: sev.dot ?? T.text.muted,
                        boxShadow: isLive && sev.dot ? `0 0 7px ${sev.dot}` : "none",
                        animation: isLive && incident.status === "investigating" ? "pulse 1.8s infinite" : "none",
                    }} />
                    <span style={{ fontSize: 12, fontFamily: T.fonts.mono, fontWeight: 700, color: T.text.primary, letterSpacing: "0.04em" }}>
                        IIQ-{shortId(incident.incident_id)}
                    </span>
                </div>
                <SeverityBadge severity={incident.severity} />
            </div>

            {/* Summary */}
            <div style={{
                fontSize: 11, color: T.text.secondary, lineHeight: 1.4, paddingLeft: 14,
                marginBottom: incident.estimated_users_affected > 0 ? 4 : 6,
                display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
            }}>
                {incident.triage_summary_snippet
                    ? incident.triage_summary_snippet
                    : <span style={{ color: T.text.disabled, fontStyle: "italic" }}>Triaging…</span>
                }
            </div>

            {/* Users affected */}
            {incident.estimated_users_affected > 0 && (
                <div style={{ paddingLeft: 14, marginBottom: 5 }}>
                    <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.severity.HIGH.fg, fontWeight: 600 }}>
                        {incident.estimated_users_affected.toLocaleString()} users
                    </span>
                </div>
            )}

            {/* Status + time */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingLeft: 14 }}>
                <StatusPill status={incident.status} />
                <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled }}>{timeAgo(incident.created_at)}</span>
            </div>
        </div>
    );
}