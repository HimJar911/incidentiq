// ─── ConnectRepo — Onboarding form ──────────────────────────────────────────
// Shown in the dashboard sidebar when no repos are connected,
// or always accessible via a "Connect Repo" button.
//
// On submit:
//   POST /api/onboard → registers GitHub webhook → saves to DynamoDB
//   Dashboard refreshes repo list and shows "Watching" status

import { useState } from "react";
import T from "../../styles/tokens";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export function ConnectRepo({ onSuccess }) {
    const [form, setForm] = useState({
        github_url: "",
        slack_webhook_url: "",
        github_token: "",
    });
    const [status, setStatus] = useState("idle"); // idle | loading | success | error
    const [errorMsg, setErrorMsg] = useState("");
    const [result, setResult] = useState(null);

    const handleChange = (field) => (e) =>
        setForm((f) => ({ ...f, [field]: e.target.value }));

    const handleSubmit = async () => {
        if (!form.github_url || !form.slack_webhook_url || !form.github_token) {
            setErrorMsg("All fields are required.");
            setStatus("error");
            return;
        }

        setStatus("loading");
        setErrorMsg("");

        try {
            const res = await fetch(`${API_BASE}/api/onboard`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(form),
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || "Onboarding failed");
            }

            setResult(data);
            setStatus("success");
            if (onSuccess) onSuccess(data);
        } catch (err) {
            setErrorMsg(err.message);
            setStatus("error");
        }
    };

    return (
        <div style={{
            background: T.bg.card,
            border: `1px solid ${T.bg.borderSubtle}`,
            borderRadius: 10,
            padding: 20,
            fontFamily: T.fonts.mono,
        }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.text.primary, marginBottom: 4 }}>
                Connect a Repository
            </div>
            <div style={{ fontSize: 11, color: T.text.muted, marginBottom: 16 }}>
                IncidentIQ will watch for bad pushes and respond automatically.
            </div>

            {/* GitHub URL */}
            <Field
                label="GitHub Repo URL"
                placeholder="https://github.com/org/repo"
                value={form.github_url}
                onChange={handleChange("github_url")}
                disabled={status === "loading" || status === "success"}
            />

            {/* Slack Webhook */}
            <Field
                label="Slack Webhook URL"
                placeholder="https://hooks.slack.com/services/..."
                value={form.slack_webhook_url}
                onChange={handleChange("slack_webhook_url")}
                disabled={status === "loading" || status === "success"}
            />

            {/* GitHub Token */}
            <Field
                label="GitHub Token"
                placeholder="ghp_..."
                value={form.github_token}
                onChange={handleChange("github_token")}
                disabled={status === "loading" || status === "success"}
                hint="Needs repo + admin:repo_hook scopes"
                isSecret
            />

            {/* Error */}
            {status === "error" && (
                <div style={{
                    fontSize: 11,
                    color: T.severity.HIGH.fg,
                    background: `${T.severity.HIGH.fg}15`,
                    border: `1px solid ${T.severity.HIGH.fg}40`,
                    borderRadius: 6,
                    padding: "8px 10px",
                    marginBottom: 12,
                }}>
                    {errorMsg}
                </div>
            )}

            {/* Success */}
            {status === "success" && result && (
                <div style={{
                    fontSize: 11,
                    color: "#10b981",
                    background: "#10b98115",
                    border: "1px solid #10b98140",
                    borderRadius: 6,
                    padding: "8px 10px",
                    marginBottom: 12,
                }}>
                    ✅ Connected <strong>{result.repo_id}</strong> — push a commit to trigger the pipeline.
                </div>
            )}

            {/* Submit button */}
            {status !== "success" && (
                <button
                    onClick={handleSubmit}
                    disabled={status === "loading"}
                    style={{
                        width: "100%",
                        padding: "9px 0",
                        background: status === "loading" ? T.bg.hover : T.accent,
                        color: "#fff",
                        border: "none",
                        borderRadius: 6,
                        fontSize: 12,
                        fontWeight: 600,
                        fontFamily: T.fonts.mono,
                        cursor: status === "loading" ? "not-allowed" : "pointer",
                        letterSpacing: "0.03em",
                    }}
                >
                    {status === "loading" ? "Connecting…" : "Connect Repository"}
                </button>
            )}

            {/* Reset after success */}
            {status === "success" && (
                <button
                    onClick={() => { setStatus("idle"); setForm({ github_url: "", slack_webhook_url: "", github_token: "" }); setResult(null); }}
                    style={{
                        width: "100%",
                        padding: "9px 0",
                        background: "transparent",
                        color: T.text.muted,
                        border: `1px solid ${T.bg.borderSubtle}`,
                        borderRadius: 6,
                        fontSize: 12,
                        fontFamily: T.fonts.mono,
                        cursor: "pointer",
                    }}
                >
                    Connect another repo
                </button>
            )}
        </div>
    );
}


// ─── Connected repos list ─────────────────────────────────────────────────────

export function ConnectedRepos({ repos, onDisconnect }) {
    if (!repos || repos.length === 0) return null;

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: T.text.disabled, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
                Watching
            </div>
            {repos.map((repo) => (
                <RepoRow key={repo.repo_id} repo={repo} onDisconnect={onDisconnect} />
            ))}
        </div>
    );
}

function RepoRow({ repo, onDisconnect }) {
    const [disconnecting, setDisconnecting] = useState(false);

    const handleDisconnect = async () => {
        if (!confirm(`Disconnect ${repo.repo_id}?`)) return;
        setDisconnecting(true);
        try {
            await fetch(`${API_BASE}/api/repos/${encodeURIComponent(repo.repo_id)}`, {
                method: "DELETE",
            });
            if (onDisconnect) onDisconnect(repo.repo_id);
        } catch (err) {
            console.error("Disconnect failed:", err);
        } finally {
            setDisconnecting(false);
        }
    };

    return (
        <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: T.bg.card,
            border: `1px solid ${T.bg.borderSubtle}`,
            borderRadius: 6,
            padding: "8px 10px",
            fontSize: 11,
            fontFamily: T.fonts.mono,
        }}>
            <div>
                <div style={{ color: T.text.primary, fontWeight: 500 }}>
                    {repo.repo_id}
                </div>
                <div style={{ color: T.text.muted, fontSize: 10, marginTop: 2 }}>
                    {repo.incident_count || 0} incidents · connected {_relativeTime(repo.connected_at)}
                </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                    width: 7, height: 7, borderRadius: "50%",
                    background: "#10b981",
                    boxShadow: "0 0 0 2px #10b98130",
                }} />
                <button
                    onClick={handleDisconnect}
                    disabled={disconnecting}
                    style={{
                        background: "transparent",
                        border: "none",
                        color: T.text.disabled,
                        fontSize: 10,
                        cursor: "pointer",
                        fontFamily: T.fonts.mono,
                        padding: "2px 4px",
                    }}
                >
                    {disconnecting ? "…" : "disconnect"}
                </button>
            </div>
        </div>
    );
}


// ─── Field helper ─────────────────────────────────────────────────────────────

function Field({ label, placeholder, value, onChange, disabled, hint, isSecret }) {
    return (
        <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: T.text.muted, marginBottom: 4, fontWeight: 500 }}>
                {label}
                {hint && <span style={{ color: T.text.disabled, marginLeft: 6 }}>— {hint}</span>}
            </div>
            <input
                type={isSecret ? "password" : "text"}
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                disabled={disabled}
                style={{
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "8px 10px",
                    background: T.bg.base,
                    border: `1px solid ${T.bg.borderSubtle}`,
                    borderRadius: 6,
                    color: T.text.primary,
                    fontSize: 11,
                    fontFamily: T.fonts.mono,
                    outline: "none",
                    opacity: disabled ? 0.5 : 1,
                }}
            />
        </div>
    );
}

function _relativeTime(iso) {
    if (!iso) return "recently";
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
}