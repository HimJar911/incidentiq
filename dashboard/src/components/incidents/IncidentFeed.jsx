// ─── IncidentFeed ──────────────────────────────────────────────────────────────

import T from "../../styles/tokens";
import { IncidentRow } from "./IncidentRow";

export function IncidentFeed({ incidents, selectedId, newIds, onSelect }) {
  if (!incidents.length) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: T.text.disabled, fontSize: 12, fontFamily: T.fonts.mono, lineHeight: 1.6 }}>
        No incidents.<br />
        Hit <span style={{ color: T.accent.primary }}>REPLAY DEMO</span> to start.
      </div>
    );
  }

  return (
    <div>
      {incidents.map(inc => (
        <IncidentRow
          key={inc.incident_id}
          incident={inc}
          selected={inc.incident_id === selectedId}
          isNew={newIds?.has(inc.incident_id) ?? false}
          onClick={() => onSelect(inc.incident_id)}
        />
      ))}
    </div>
  );
}