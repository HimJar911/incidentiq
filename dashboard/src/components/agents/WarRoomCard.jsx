// ─── WarRoomCard ───────────────────────────────────────────────────────────────
// Appears when status reaches war_room_posted.
// This is the "money moment" — shows users impacted prominently.

import T from "../../styles/tokens";

export function WarRoomCard({ incident }) {
    const users = incident.estimated_users_affected ?? 0;
    const slackId = incident.slack_message_id;
    const visible = ["war_room_posted", "resolved", "postmortem_ready"].includes(incident.status);

    if (!visible) return null;

    const impactKey = slackId ?? incident.status;

    return (
        <div style={{
            background: "rgba(167,139,250,0.04)",
            border: "1px solid rgba(167,139,250,0.18)",
            borderRadius: 8, padding: "14px 18px",
            display: "flex", alignItems: "center", justifyContent: "space-between",
            animation: "fadeIn 0.5s ease",
        }}>
            {/* Left: icon + info */}
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{
                    width: 38, height: 38, borderRadius: 9, flexShrink: 0,
                    background: "rgba(167,139,250,0.1)", border: "1px solid rgba(167,139,250,0.2)",
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17,
                }}>💬</div>
                <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                        <span style={{ fontSize: 11, fontFamily: T.fonts.mono, fontWeight: 700, color: "#A78BFA", letterSpacing: "0.08em" }}>
                            WAR ROOM POSTED
                        </span>
                        <span style={{ fontSize: 9, fontFamily: T.fonts.mono, color: T.text.disabled, background: T.bg.raised, border: `1px solid ${T.bg.border}`, borderRadius: 3, padding: "1px 6px" }}>
                            via communication_agent
                        </span>
                    </div>
                    <div style={{ fontSize: 11, color: T.text.secondary }}>
                        Slack brief dispatched
                        {slackId && (
                            <span style={{ fontFamily: T.fonts.mono, color: T.text.muted, marginLeft: 6 }}>
                                · {slackId.split("/").pop()?.slice(1, 11)}
                            </span>
                        )}
                    </div>
                </div>
            </div>

            {/* Right: users impacted — the money number */}
            {users > 0 && (
                <div key={impactKey} style={{ textAlign: "right", flexShrink: 0, animation: "impactReveal 0.7s cubic-bezier(0.22,1,0.36,1)" }}>
                    <div style={{
                        fontSize: 32, fontFamily: T.fonts.mono, fontWeight: 700,
                        color: T.severity.HIGH.fg, lineHeight: 1,
                        letterSpacing: "-0.03em",
                        textShadow: `0 0 24px ${T.severity.HIGH.dot}55`,
                    }}>
                        {users.toLocaleString()}
                    </div>
                    <div style={{ fontSize: 10, fontFamily: T.fonts.mono, color: T.text.muted, letterSpacing: "0.1em", marginTop: 3 }}>
                        USERS IMPACTED
                    </div>
                </div>
            )}
        </div>
    );
}