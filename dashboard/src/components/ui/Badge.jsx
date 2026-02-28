// ─── Badge Components ──────────────────────────────────────────────────────────

import T from "../../styles/tokens";

export function SeverityBadge({ severity }) {
    if (!severity) return null;
    const s = T.severity[severity];
    if (!s) return null;
    return (
        <span style={{
            fontSize: 10, fontFamily: T.fonts.mono, fontWeight: 700, letterSpacing: "0.1em",
            color: s.fg, background: s.bg, border: `1px solid ${s.border}`,
            borderRadius: 3, padding: "2px 8px", flexShrink: 0,
            whiteSpace: "nowrap",
        }}>
            {severity}
        </span>
    );
}

export function StatusPill({ status }) {
    const color = T.statusColors[status] ?? T.text.muted;
    const label = T.statusLabels[status] ?? status?.toUpperCase() ?? "—";
    return (
        <span style={{
            fontSize: 10, fontFamily: T.fonts.mono, fontWeight: 600,
            letterSpacing: "0.08em", color,
        }}>
            {label}
        </span>
    );
}

export function SourceBadge({ source }) {
    return (
        <span style={{
            fontSize: 10, fontFamily: T.fonts.mono, color: T.text.muted,
            background: T.bg.raised, border: `1px solid ${T.bg.border}`,
            borderRadius: 3, padding: "2px 7px", whiteSpace: "nowrap",
        }}>
            {source}
        </span>
    );
}
