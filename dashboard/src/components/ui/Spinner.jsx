// ─── Spinner ───────────────────────────────────────────────────────────────────

import T from "../../styles/tokens";

export function Spinner({ size = 16, color }) {
    return (
        <span style={{
            display: "inline-block",
            width: size, height: size,
            fontSize: size,
            lineHeight: 1,
            color: color ?? T.accent.primary,
            fontFamily: T.fonts.mono,
            animation: "spin 0.8s linear infinite",
        }}>
            ◌
        </span>
    );
}
