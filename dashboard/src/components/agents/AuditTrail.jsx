// ─── AuditTrail ────────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { Panel } from "../ui/Panel";
import { SeverityBadge } from "../ui/Badge";

function fmtTime(iso) {
    return iso ? new Date(iso).toISOString().slice(11, 19) : "";
}

export function AuditEntry({ entry, index }) {
    const color = T.agentColors[entry.agent] ?? T.text.muted;

    return (
        <div style={{
            display: "grid", gridTemplateColumns: "58px 148px 1fr",
            gap: 12, padding: "6px 0",
            borderBottom: `1px solid ${T.bg.borderSubtle}`,
            animation: `fadeIn 0.2s ease ${index * 0.025}s both`,
        }}>
            <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled, paddingTop: 1 }}>
                {fmtTime(entry.ts)}
            </span>
            <span style={{ fontSize: 10, fontFamily: T.fonts.mono, color, fontWeight: 600, paddingTop: 1 }}>
                {entry.agent}
            </span>
            <span style={{ fontSize: 11, color: T.text.secondary, lineHeight: 1.5 }}>
                {entry.action_type}
                {entry.details?.new_status && (
                    <span style={{ marginLeft: 6, color: T.statusColors[entry.details.new_status], fontSize: 10 }}>
                        → {entry.details.new_status}
                    </span>
                )}
                {entry.details?.severity && (
                    <span style={{ marginLeft: 6 }}>
                        <SeverityBadge severity={entry.details.severity} />
                    </span>
                )}
                {entry.details?.suspect_count > 0 && (
                    <span style={{ marginLeft: 6, color: T.agentColors.investigation_agent, fontSize: 10 }}>
                        {entry.details.suspect_count} suspects found
                    </span>
                )}
                {entry.details?.hits_count > 0 && (
                    <span style={{ marginLeft: 6, color: T.agentColors.runbook_agent, fontSize: 10 }}>
                        {entry.details.hits_count} runbooks matched
                    </span>
                )}
                {entry.details?.estimated_users_affected > 0 && (
                    <span style={{ marginLeft: 6, color: T.severity.HIGH.fg, fontSize: 10 }}>
                        ~{entry.details.estimated_users_affected.toLocaleString()} users affected
                    </span>
                )}
                {entry.details?.error && (
                    <span style={{ marginLeft: 6, color: T.severity.HIGH.fg, fontSize: 10 }}>
                        ✗ {entry.details.error.slice(0, 80)}
                    </span>
                )}
            </span>
        </div>
    );
}

export function AuditTrail({ log = [] }) {
    return (
        <Panel
            title="Agent Audit Trail"
            topRight={<span style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.disabled }}>{log.length} events</span>}
        >
            <div style={{ padding: "10px 16px" }}>
                {!log.length
                    ? <div style={{ fontSize: 11, color: T.text.disabled, padding: "8px 0", fontStyle: "italic" }}>Awaiting agent activity…</div>
                    : [...log].reverse().map((entry, i) => <AuditEntry key={i} entry={entry} index={i} />)
                }
            </div>
        </Panel>
    );
}