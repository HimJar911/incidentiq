// ─── BlastRadius ───────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { Panel } from "../ui/Panel";
import { Tag } from "../ui/Tag";
import { ConfidenceBar } from "../ui/ConfidenceBar";

export function BlastRadius({ services = [] }) {
    return (
        <Panel title="Blast Radius">
            <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {services.length
                        ? services.map(s => <Tag key={s}>{s}</Tag>)
                        : <span style={{ fontSize: 11, color: T.text.disabled, fontStyle: "italic" }}>Analyzing…</span>
                    }
                </div>
                {services.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: `1px solid ${T.bg.borderSubtle}`, paddingTop: 10 }}>
                        {services.slice(0, 5).map((s, i) => (
                            <ConfidenceBar
                                key={s}
                                label={s}
                                value={Math.max(35, 95 - i * 13)}
                                color={T.severity.HIGH.fg}
                            />
                        ))}
                    </div>
                )}
            </div>
        </Panel>
    );
}