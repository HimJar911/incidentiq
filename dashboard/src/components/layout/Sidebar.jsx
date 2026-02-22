// ─── Sidebar ───────────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { IncidentFeed } from "../incidents/IncidentFeed";

export function Sidebar({ incidents, selectedId, newIds, onSelect }) {
    return (
        <aside style={{
            borderRight: `1px solid ${T.bg.border}`,
            display: "flex", flexDirection: "column",
            overflow: "hidden",
            width: 300, flexShrink: 0,
        }}>
            {/* Header */}
            <div style={{
                padding: "10px 16px", flexShrink: 0,
                borderBottom: `1px solid ${T.bg.borderSubtle}`,
                display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
                <span style={{
                    fontSize: 10, fontFamily: T.fonts.mono, fontWeight: 700,
                    letterSpacing: "0.1em", color: T.text.disabled,
                }}>
                    INCIDENTS · {incidents.length}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#34D399", animation: "pulse 2.5s infinite" }} />
                    <span style={{ fontSize: 9, fontFamily: T.fonts.mono, color: T.text.disabled }}>LIVE</span>
                </div>
            </div>

            {/* Feed */}
            <div style={{ flex: 1, overflowY: "auto" }}>
                <IncidentFeed
                    incidents={incidents}
                    selectedId={selectedId}
                    newIds={newIds}
                    onSelect={onSelect}
                />
            </div>
        </aside>
    );
}