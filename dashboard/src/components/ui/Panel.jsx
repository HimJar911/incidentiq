// ─── Panel ─────────────────────────────────────────────────────────────────────
// Neutral card container. No accent borders — color lives inside content only.

import T from "../styles/tokens";

export function Panel({ title, topRight, children, style = {} }) {
    return (
        <div style={{
            background: T.bg.surface,
            border: `1px solid ${T.bg.border}`,
            borderRadius: 8,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            ...style,
        }}>
            <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "10px 16px",
                borderBottom: `1px solid ${T.bg.borderSubtle}`,
                flexShrink: 0,
            }}>
                <span style={{
                    fontSize: 10, fontFamily: T.fonts.mono, fontWeight: 700,
                    letterSpacing: "0.12em", color: T.text.muted, textTransform: "uppercase",
                }}>
                    {title}
                </span>
                {topRight}
            </div>
            <div style={{ flex: 1, overflow: "auto" }}>
                {children}
            </div>
        </div>
    );
}