// ─── TopBar ────────────────────────────────────────────────────────────────────

import { useState } from "react";
import T from "../../styles/tokens";
import { Spinner } from "../ui/Spinner";
import { triggerReplay } from "../../api/incidentApi";

export function TopBar({ activeCount, highCount, totalImpact, onReplaySuccess }) {
    const [replayState, setReplayState] = useState(null); // null | "firing" | "done"
    const now = new Date().toISOString().slice(11, 19);

    const handleReplay = async () => {
        setReplayState("firing");
        try {
            const data = await triggerReplay("payments_service_high");
            onReplaySuccess?.(data.incident_id);
            setReplayState("done");
            setTimeout(() => setReplayState(null), 3500);
        } catch (err) {
            console.error("[TopBar] Replay failed:", err);
            setReplayState(null);
        }
    };

    return (
        <header style={{
            height: 52, display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "0 20px", flexShrink: 0,
            background: T.bg.surface, borderBottom: `1px solid ${T.bg.border}`,
        }}>
            {/* Left: Logo + stats */}
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>

                {/* Logo */}
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                        width: 30, height: 30, borderRadius: 8, flexShrink: 0,
                        background: `linear-gradient(135deg, ${T.accent.primary}, #7C3AED)`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 14, color: "#fff", fontWeight: 800,
                        boxShadow: `0 0 18px ${T.accent.glow}`,
                    }}>⬡</div>
                    <div>
                        <div style={{ fontSize: 13, fontFamily: T.fonts.mono, fontWeight: 700, letterSpacing: "0.1em", color: T.text.primary }}>
                            INCIDENTIQ
                        </div>
                        <div style={{ fontSize: 9, fontFamily: T.fonts.mono, color: T.text.disabled, letterSpacing: "0.06em" }}>
                            AUTONOMOUS RESPONSE · NOVA 2
                        </div>
                    </div>
                </div>

                <div style={{ width: 1, height: 26, background: T.bg.border }} />

                {/* Stats */}
                <div style={{ display: "flex", gap: 24 }}>
                    {[
                        { label: "ACTIVE", value: activeCount, color: activeCount > 0 ? T.severity.MED.fg : T.text.disabled },
                        { label: "HIGH SEV", value: highCount, color: highCount > 0 ? T.severity.HIGH.fg : T.text.disabled },
                        {
                            label: "IMPACTED",
                            value: totalImpact > 0 ? `${(totalImpact / 1000).toFixed(1)}k` : "0",
                            color: totalImpact > 0 ? T.severity.HIGH.fg : T.text.disabled,
                        },
                    ].map(({ label, value, color }) => (
                        <div key={label} style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                            <span style={{ fontSize: 9, fontFamily: T.fonts.mono, letterSpacing: "0.08em", color: T.text.disabled }}>{label}</span>
                            <span key={String(value)} style={{ fontSize: 15, fontFamily: T.fonts.mono, fontWeight: 700, color, animation: "countUp 0.35s ease" }}>
                                {value}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Right: Clock + Replay */}
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#34D399", animation: "pulse 2s infinite" }} />
                    <span style={{ fontSize: 11, fontFamily: T.fonts.mono, color: T.text.muted, letterSpacing: "0.08em" }}>
                        {now} UTC{" "}
                        <span style={{ animation: "blink 1s infinite", display: "inline-block" }}>▎</span>
                    </span>
                </div>

                <button
                    onClick={handleReplay}
                    disabled={replayState === "firing"}
                    style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "7px 16px", borderRadius: 6,
                        background: T.accent.dim, border: `1px solid ${T.accent.border}`,
                        color: T.accent.primary, fontSize: 11, fontFamily: T.fonts.mono,
                        fontWeight: 700, letterSpacing: "0.08em",
                        boxShadow: replayState === "firing" ? "none" : `0 0 18px ${T.accent.glow}`,
                    }}
                >
                    {replayState === "firing" ? <Spinner size={11} /> : "▶"}
                    {replayState === "firing" ? "FIRING…" : "REPLAY DEMO"}
                </button>
            </div>
        </header>
    );
}