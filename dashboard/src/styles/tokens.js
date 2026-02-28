// ─── IncidentIQ Design Tokens ─────────────────────────────────────────────────
// Every color, font, and config value lives here.
// Nothing is hardcoded in components.

export const colors = {
    bg: {
        base: "#0F1117",
        surface: "#161B27",
        raised: "#1C2333",
        overlay: "#212840",
        border: "#1E2535",
        borderSubtle: "#171E2C",
    },
    text: {
        primary: "#E8EDF5",
        secondary: "#8B98B1",
        muted: "#6B7A99",      // was #4A5568
        disabled: "#4A5568",   // was #2D3748
    },
    accent: {
        primary: "#5B8DEF",
        dim: "rgba(91,141,239,0.12)",
        border: "rgba(91,141,239,0.28)",
        glow: "rgba(91,141,239,0.18)",
    },
};

export const severity = {
    HIGH: {
        fg: "#F87171",
        bg: "rgba(248,113,113,0.07)",
        border: "rgba(248,113,113,0.2)",
        dot: "#EF4444",
    },
    MED: {
        fg: "#FBBF24",
        bg: "rgba(251,191,36,0.07)",
        border: "rgba(251,191,36,0.2)",
        dot: "#F59E0B",
    },
    LOW: {
        fg: "#34D399",
        bg: "rgba(52,211,153,0.07)",
        border: "rgba(52,211,153,0.2)",
        dot: "#10B981",
    },
};

export const statusColors = {
    ingested: "#2D3748",
    triaged: "#5B8DEF",
    investigating: "#FBBF24",
    war_room_posted: "#A78BFA",
    resolved: "#34D399",
    postmortem_ready: "#34D399",
};

export const statusLabels = {
    ingested: "INGESTED",
    triaged: "TRIAGED",
    investigating: "INVESTIGATING",
    war_room_posted: "WAR ROOM",
    resolved: "RESOLVED",
    postmortem_ready: "POSTMORTEM READY",
};

export const agentColors = {
    triage_agent: "#5B8DEF",
    investigation_agent: "#FBBF24",
    runbook_agent: "#A78BFA",
    communication_agent: "#34D399",
    postmortem_agent: "#F472B6",
    orchestrator: "#4A5568",
    api: "#4A5568",
};

export const fonts = {
    mono: "'JetBrains Mono', 'Fira Code', monospace",
    sans: "'Inter', system-ui, sans-serif",
};

export const pipelineSteps = [
    { key: "ingested", label: "INGEST" },
    { key: "triaged", label: "TRIAGE" },
    { key: "investigating", label: "INVESTIGATE" },
    { key: "war_room_posted", label: "WAR ROOM" },
    { key: "resolved", label: "RESOLVED" },
    { key: "postmortem_ready", label: "POSTMORTEM" },
];

export const statusStep = {
    ingested: 0,
    triaged: 1,
    investigating: 2,
    war_room_posted: 3,
    resolved: 4,
    postmortem_ready: 5,
};

// Convenience alias — import T from tokens and use T.bg, T.text, etc.
const T = { ...colors, severity, statusColors, statusLabels, agentColors, fonts, pipelineSteps, statusStep };
export default T;