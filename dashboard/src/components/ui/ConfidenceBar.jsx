// ─── ConfidenceBar ─────────────────────────────────────────────────────────────

import T from "../styles/tokens";

export function ConfidenceBar({ label, value, color }) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {label && (
                <span style={{
                    width: 130, fontSize: 10, fontFamily: T.fonts.mono,
                    color: T.text.secondary, flexShrink: 0,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                    {label}
                </span>
            )}
            <div style={{ flex: 1, height: 3, background: T.bg.raised, borderRadius: 2, overflow: "hidden" }}>
                <div style={{
                    height: "100%", width: `${Math.min(100, Math.max(0, value))}%`,
                    background: color ?? T.accent.primary,
                    borderRadius: 2, transition: "width 0.6s ease",
                }} />
            </div>
            <span style={{
                fontSize: 10, fontFamily: T.fonts.mono,
                color: T.text.muted, width: 32, textAlign: "right",
            }}>
                {value}%
            </span>
        </div>
    );
}