// ─── SuspectCommits ────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { Panel } from "../ui/Panel";
import { ConfidenceBar } from "../ui/ConfidenceBar";

export function CommitCard({ commit }) {
    return (
        <div style={{
            display: "grid", gridTemplateColumns: "64px 1fr 140px",
            gap: 14, padding: "10px 12px",
            background: T.bg.raised, border: `1px solid ${T.bg.border}`,
            borderRadius: 6, alignItems: "center",
        }}>
            <span style={{ fontSize: 12, fontFamily: T.fonts.mono, color: T.severity.MED.fg, fontWeight: 700 }}>
                {commit.sha?.slice(0, 7) ?? "???????"}
            </span>
            <div>
                <div style={{ fontSize: 12, color: T.text.primary, marginBottom: 3 }}>{commit.message}</div>
                <div style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.muted }}>
                    {commit.author}{commit.repo ? ` · ${commit.repo}` : ""}
                </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 9, fontFamily: T.fonts.mono, color: T.text.disabled, textAlign: "right" }}>CONFIDENCE</span>
                <ConfidenceBar value={Math.round((commit.confidence ?? 0) * 100)} color={T.severity.MED.fg} />
            </div>
        </div>
    );
}

export function SuspectCommits({ commits = [] }) {
    if (!commits.length) return null;
    return (
        <Panel
            title="Suspect Commits"
            topRight={<span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled }}>{commits.length} flagged</span>}
        >
            <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
                {commits.map((c, i) => <CommitCard key={c.sha ?? i} commit={c} />)}
            </div>
        </Panel>
    );
}