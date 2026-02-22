// ─── PipelineTracker ───────────────────────────────────────────────────────────

import T from "../../styles/tokens";

export function PipelineTracker({ status, prevStatus }) {
    const current = T.statusStep[status] ?? 0;
    const prev = T.statusStep[prevStatus] ?? current;
    const justAdvanced = current > prev;

    return (
        <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
            {T.pipelineSteps.map((step, i) => {
                const done = i <= current;
                const active = i === current;
                const justLit = justAdvanced && i === current;
                const color = T.statusColors[step.key] ?? T.text.muted;

                return (
                    <div key={step.key} style={{ display: "flex", alignItems: "center", flex: i < T.pipelineSteps.length - 1 ? 1 : "none" }}>
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
                            {/* Step node */}
                            <div style={{
                                width: 30, height: 30, borderRadius: 7,
                                border: `1px solid ${done ? color : T.bg.border}`,
                                background: active ? `${color}22` : done ? `${color}0E` : "transparent",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                boxShadow: active
                                    ? `0 0 0 1px ${color}30, 0 0 18px ${color}50, 0 0 32px ${color}20`
                                    : "none",
                                animation: justLit ? "stepBurst 0.6s ease" : "none",
                                transition: "all 0.45s ease",
                            }}>
                                {i < current ? (
                                    <span style={{ color, fontSize: 12, fontFamily: T.fonts.mono }}>✓</span>
                                ) : (
                                    <div style={{
                                        width: active ? 8 : 5,
                                        height: active ? 8 : 5,
                                        borderRadius: "50%",
                                        background: done ? color : T.bg.overlay,
                                        boxShadow: active ? `0 0 6px ${color}` : "none",
                                        transition: "all 0.45s ease",
                                    }} />
                                )}
                            </div>

                            {/* Label */}
                            <span style={{
                                fontSize: 9, fontFamily: T.fonts.mono, letterSpacing: "0.08em",
                                color: done ? color : T.text.disabled,
                                fontWeight: active ? 700 : 400,
                                whiteSpace: "nowrap",
                                transition: "all 0.45s ease",
                            }}>
                                {step.label}
                            </span>
                        </div>

                        {/* Connector line */}
                        {i < T.pipelineSteps.length - 1 && (
                            <div style={{
                                flex: 1, height: 1, marginBottom: 18,
                                background: i < current
                                    ? `linear-gradient(90deg, ${T.statusColors[T.pipelineSteps[i].key] ?? ""}, ${T.statusColors[T.pipelineSteps[i + 1].key] ?? ""})`
                                    : T.bg.border,
                                transition: "background 0.5s ease",
                            }} />
                        )}
                    </div>
                );
            })}
        </div>
    );
}