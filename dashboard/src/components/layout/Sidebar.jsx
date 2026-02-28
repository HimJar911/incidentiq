// ─── Sidebar ───────────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { IncidentFeed } from "../incidents/IncidentFeed";
import { ConnectRepo, ConnectedRepos } from "../onboarding/ConnectRepo";
import { useRepos } from "../../hooks/useRepos";

export function Sidebar({ incidents, selectedId, newIds, onSelect }) {
    const {
        repos,
        showForm,
        setShowForm,
        handleDisconnect,
        handleConnectSuccess,
    } = useRepos();

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

            {/* Onboarding — connected repos + connect form */}
            <div style={{
                padding: "12px 12px 0",
                flexShrink: 0,
                borderBottom: `1px solid ${T.bg.borderSubtle}`,
                paddingBottom: 12,
            }}>
                <ConnectedRepos repos={repos} onDisconnect={handleDisconnect} />

                {!showForm ? (
                    <button
                        onClick={() => setShowForm(true)}
                        style={{
                            width: "100%",
                            marginTop: repos.length > 0 ? 8 : 0,
                            padding: "8px 0",
                            background: "transparent",
                            border: `1px dashed ${T.bg.border}`,
                            borderRadius: 6,
                            color: T.text.disabled,
                            fontSize: 11,
                            fontFamily: T.fonts.mono,
                            cursor: "pointer",
                        }}
                    >
                        + Connect Repository
                    </button>
                ) : (
                    <div style={{ marginTop: repos.length > 0 ? 8 : 0 }}>
                        <ConnectRepo onSuccess={handleConnectSuccess} />
                        {repos.length > 0 && (
                            <button
                                onClick={() => setShowForm(false)}
                                style={{
                                    marginTop: 6,
                                    background: "transparent",
                                    border: "none",
                                    color: T.text.disabled,
                                    fontSize: 10,
                                    cursor: "pointer",
                                    fontFamily: T.fonts.mono,
                                    width: "100%",
                                }}
                            >
                                cancel
                            </button>
                        )}
                    </div>
                )}
            </div>

            {/* Incident feed */}
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