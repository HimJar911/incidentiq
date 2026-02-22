// ─── PostmortemRenderer ────────────────────────────────────────────────────────
// Renders postmortem markdown as styled JSX.

import T from "../../styles/tokens";

export function PostmortemRenderer({ content }) {
    if (!content) return null;

    return (
        <div style={{ fontFamily: T.fonts.sans }}>
            {content.split("\n").map((line, i) => {
                if (line.startsWith("# ")) return (
                    <h1 key={i} style={{ color: T.text.primary, fontSize: 18, fontFamily: T.fonts.mono, marginBottom: 8, paddingBottom: 12, borderBottom: `1px solid ${T.bg.border}` }}>
                        {line.slice(2)}
                    </h1>
                );
                if (line.startsWith("## ")) return (
                    <h2 key={i} style={{ color: T.accent.primary, fontSize: 10, fontFamily: T.fonts.mono, fontWeight: 700, letterSpacing: "0.12em", marginTop: 20, marginBottom: 8 }}>
                        {line.slice(3).toUpperCase()}
                    </h2>
                );
                if (line.startsWith("### ")) return (
                    <h3 key={i} style={{ color: T.text.secondary, fontSize: 12, fontFamily: T.fonts.mono, marginTop: 14, marginBottom: 6 }}>
                        {line.slice(4)}
                    </h3>
                );
                if (line.startsWith("> ")) return (
                    <blockquote key={i} style={{ borderLeft: `3px solid ${T.bg.border}`, margin: "8px 0", padding: "4px 12px", color: T.text.muted, fontSize: 12 }}>
                        {line.slice(2)}
                    </blockquote>
                );
                if (line.startsWith("- [ ] ") || line.startsWith("* [ ] ")) return (
                    <div key={i} style={{ display: "flex", gap: 8, color: T.text.secondary, fontSize: 13, marginBottom: 5, paddingLeft: 8 }}>
                        <span style={{ color: T.bg.border, flexShrink: 0 }}>☐</span>
                        {line.slice(6)}
                    </div>
                );
                if (line.startsWith("- ") || line.startsWith("* ")) return (
                    <div key={i} style={{ display: "flex", gap: 8, color: T.text.secondary, fontSize: 13, marginBottom: 4, paddingLeft: 8 }}>
                        <span style={{ color: T.text.disabled, flexShrink: 0 }}>›</span>
                        <span dangerouslySetInnerHTML={{ __html: line.slice(2).replace(/\*\*(.*?)\*\*/g, `<strong style="color:${T.text.primary}">$1</strong>`) }} />
                    </div>
                );
                if (line.startsWith("---")) return (
                    <hr key={i} style={{ border: "none", borderTop: `1px solid ${T.bg.border}`, margin: "12px 0" }} />
                );
                if (line === "") return <div key={i} style={{ height: 8 }} />;
                return (
                    <p key={i} style={{ color: T.text.secondary, fontSize: 13, lineHeight: 1.7, marginBottom: 4 }}
                        dangerouslySetInnerHTML={{ __html: line.replace(/\*\*(.*?)\*\*/g, `<strong style="color:${T.text.primary}">$1</strong>`) }}
                    />
                );
            })}
        </div>
    );
}