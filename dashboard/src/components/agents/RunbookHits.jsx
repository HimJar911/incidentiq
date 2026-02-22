// ─── RunbookHits ───────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { Panel } from "../ui/Panel";

export function RunbookCard({ hit }) {
    return (
        <div style={{
            padding: "10px 12px", background: T.bg.raised,
            border: `1px solid ${T.bg.border}`, borderRadius: 6,
        }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontSize: 10, fontFamily: T.fonts.mono, fontWeight: 700, color: T.accent.primary }}>
                    {hit.runbook_id}
                </span>
                {hit.relevance != null && (
                    <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled }}>
                        {Math.round(hit.relevance * 100)}% match
                    </span>
                )}
            </div>
            <div style={{ fontSize: 11, color: T.text.secondary, marginBottom: hit.first_action_step ? 6 : 0 }}>
                {hit.section}
            </div>
            {hit.first_action_step && (
                <div style={{
                    fontSize: 10, fontFamily: T.fonts.mono, color: T.text.muted,
                    paddingLeft: 8, borderLeft: `2px solid ${T.bg.border}`,
                }}>
                    › {hit.first_action_step}
                </div>
            )}
        </div>
    );
}

export function RunbookHits({ hits = [] }) {
    return (
        <Panel
            title="Runbook Hits"
            topRight={
                hits.length > 0
                    ? <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled }}>{hits.length} matched</span>
                    : null
            }
        >
            <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
                {hits.length
                    ? hits.map((hit, i) => <RunbookCard key={hit.runbook_id ?? i} hit={hit} />)
                    : <span style={{ fontSize: 11, color: T.text.disabled, fontStyle: "italic" }}>Searching knowledge base…</span>
                }
            </div>
        </Panel>
    );
}