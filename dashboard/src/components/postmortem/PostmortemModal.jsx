// ─── PostmortemModal ───────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { usePostmortem } from "../../hooks/usePostmortem";
import { PostmortemRenderer } from "./PostmortemRenderer";
import { SeverityBadge } from "../ui/Badge";
import { Spinner } from "../ui/Spinner";

function shortId(id) { return id?.slice(0, 8).toUpperCase() ?? "—"; }

export function PostmortemModal({ incident, onClose }) {
    const { content, loading, error } = usePostmortem(incident.incident_id, true);

    return (
        <div
            style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.82)", backdropFilter: "blur(5px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}
            onClick={onClose}
        >
            <div
                style={{ background: T.bg.surface, border: `1px solid ${T.bg.border}`, borderRadius: 10, width: "100%", maxWidth: 740, maxHeight: "84vh", display: "flex", flexDirection: "column", boxShadow: "0 32px 80px rgba(0,0,0,0.7)" }}
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: `1px solid ${T.bg.border}`, flexShrink: 0 }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <span style={{ fontSize: 11, fontFamily: T.fonts.mono, fontWeight: 700, color: "#F472B6", letterSpacing: "0.1em" }}>▣ POSTMORTEM</span>
                        <span style={{ fontSize: 11, fontFamily: T.fonts.mono, color: T.text.disabled }}>IIQ-{shortId(incident.incident_id)}</span>
                        <SeverityBadge severity={incident.severity} />
                    </div>
                    <button onClick={onClose} style={{ background: "none", border: `1px solid ${T.bg.border}`, color: T.text.muted, borderRadius: 4, padding: "4px 12px", fontSize: 11, fontFamily: T.fonts.mono }}>
                        ESC
                    </button>
                </div>

                {/* Body */}
                <div style={{ flex: 1, overflow: "auto", padding: "24px 28px" }}>
                    {loading && (
                        <div style={{ display: "flex", alignItems: "center", gap: 10, color: T.text.disabled, fontSize: 12, fontFamily: T.fonts.mono, paddingTop: 40 }}>
                            <Spinner size={14} /> Loading postmortem…
                        </div>
                    )}
                    {error && (
                        <div style={{ color: T.severity.HIGH.fg, fontSize: 12, fontFamily: T.fonts.mono }}>
                            Error: {error}
                        </div>
                    )}
                    {content && <PostmortemRenderer content={content} />}
                </div>
            </div>
        </div>
    );
}