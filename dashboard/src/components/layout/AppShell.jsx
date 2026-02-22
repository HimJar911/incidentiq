// ─── AppShell ──────────────────────────────────────────────────────────────────
// Outer layout wrapper. Composes TopBar + Sidebar + main content slot.

import { useState } from "react";
import T from "../../styles/tokens";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { Toast } from "../ui/Toast";

export function AppShell({ incidents, activeCount, highCount, totalImpact, selectedId, newIds, onSelect, onReplaySuccess, children }) {
    const [toast, setToast] = useState(null);

    const handleReplaySuccess = (incidentId) => {
        setToast("Incident created — pipeline starting…");
        setTimeout(() => setToast(null), 3500);
        onReplaySuccess?.(incidentId);
    };

    return (
        <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: T.bg.base, color: T.text.primary }}>
            <TopBar
                activeCount={activeCount}
                highCount={highCount}
                totalImpact={totalImpact}
                onReplaySuccess={handleReplaySuccess}
            />

            <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
                <Sidebar
                    incidents={incidents}
                    selectedId={selectedId}
                    newIds={newIds}
                    onSelect={onSelect}
                />
                <main style={{ flex: 1, overflowY: "auto" }}>
                    {children}
                </main>
            </div>

            <Toast message={toast} visible={!!toast} />
        </div>
    );
}