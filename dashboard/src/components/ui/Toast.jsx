// ─── Toast ─────────────────────────────────────────────────────────────────────

import T from "../../styles/tokens";

export function Toast({ message, visible }) {
    if (!visible || !message) return null;
    return (
        <div style={{
            position: "fixed", bottom: 24, right: 24, zIndex: 200,
            background: T.bg.raised,
            border: `1px solid ${T.accent.border}`,
            borderRadius: 6, padding: "10px 16px",
            fontSize: 11, fontFamily: T.fonts.mono, color: T.accent.primary,
            boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
            animation: "toastIn 0.3s ease",
        }}>
            ▶ {message}
        </div>
    );
}
