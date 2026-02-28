// ─── Tag ───────────────────────────────────────────────────────────────────────

import T from "../../styles/tokens";

export function Tag({ children }) {
    return (
        <span style={{
            fontSize: 10, fontFamily: T.fonts.mono,
            color: T.text.secondary,
            background: T.bg.raised,
            border: `1px solid ${T.bg.border}`,
            borderRadius: 3, padding: "2px 7px",
            whiteSpace: "nowrap",
        }}>
            {children}
        </span>
    );
}
