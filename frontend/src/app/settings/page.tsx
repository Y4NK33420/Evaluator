"use client";
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
    Settings, User, Globe, Server, CheckCircle,
    XCircle, AlertTriangle, LogOut,
} from "lucide-react";
import { PageShell, Sidebar } from "@/components/layout/Shell";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

const SIDEBAR_ITEMS = [
    { href: "/settings", label: "Profile", icon: User },
    { href: "/settings/system", label: "System", icon: Server },
];

export default function SettingsPage() {
    const { actor, courseId, logout } = useAuth();
    const [name, setName] = useState(actor ?? "");
    const [saved, setSaved] = useState(false);

    const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health.get });
    const { data: classroom } = useQuery({ queryKey: ["classroom-auth"], queryFn: api.classroom.authStatus });
    const { data: runtime } = useQuery({ queryKey: ["runtime-status"], queryFn: api.codeEval.runtimeStatus });

    const saveProfile = () => {
        localStorage.setItem("amgs_actor", name.trim());
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
    };

    return (
        <PageShell sidebar={<Sidebar items={SIDEBAR_ITEMS} />}>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Settings</h1>
                    <p className="page-subtitle">Profile, system health, and integrations</p>
                </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-6)" }}>

                {/* Profile */}
                <div className="card">
                    <h2 className="section-title" style={{ marginBottom: "var(--space-4)" }}>
                        <User size={14} style={{ display: "inline", marginRight: 6 }} /> Profile
                    </h2>
                    <div className="flex flex-col gap-4">
                        <div className="input-group">
                            <label className="input-label">Your Name</label>
                            <input className="input" value={name} onChange={e => setName(e.target.value)} />
                        </div>
                        <div className="input-group">
                            <label className="input-label">Course ID</label>
                            <input className="input" value={courseId ?? ""} disabled style={{ opacity: 0.5 }} />
                            <span className="input-hint">Log out and log in again to change Course ID.</span>
                        </div>
                        <div className="flex items-center gap-3">
                            <button className="btn btn-primary" onClick={saveProfile}>{saved ? "Saved ✓" : "Save Name"}</button>
                            <button className="btn btn-danger" onClick={logout}>
                                <LogOut size={13} /> Sign Out
                            </button>
                        </div>
                    </div>
                </div>

                {/* Google Classroom */}
                <div className="card">
                    <h2 className="section-title" style={{ marginBottom: "var(--space-4)" }}>
                        <Globe size={14} style={{ display: "inline", marginRight: 6 }} /> Google Classroom
                    </h2>
                    <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-4)" }}>
                        {classroom?.authenticated
                            ? <CheckCircle size={18} style={{ color: "var(--success)" }} />
                            : <XCircle size={18} style={{ color: "var(--danger)" }} />}
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 600 }}>
                                {classroom?.authenticated ? "Connected" : "Not Connected"}
                            </div>
                            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                {classroom?.authenticated
                                    ? `${classroom?.scopes?.length ?? 0} OAuth scopes active`
                                    : "Place token.json in backend/app/services/google_auth/"}
                            </div>
                        </div>
                    </div>
                    {(classroom?.scopes?.length ?? 0) > 0 && (
                        <div className="flex flex-col gap-2">
                            {(classroom?.friendly_scopes ?? classroom?.scopes ?? []).map((s: string, i: number) => (
                                <div key={i} style={{
                                    fontSize: 11, color: "var(--text-muted)",
                                    padding: "3px var(--space-3)",
                                    borderRadius: "var(--radius-sm)",
                                    background: "var(--bg-elevated)",
                                    fontFamily: classroom?.friendly_scopes ? undefined : "var(--font-mono)",
                                    display: "flex", alignItems: "center", gap: "var(--space-2)",
                                }}>
                                    <CheckCircle size={10} style={{ color: "var(--success)", flexShrink: 0 }} />
                                    {s}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* System health */}
                <div className="card">
                    <h2 className="section-title" style={{ marginBottom: "var(--space-4)" }}>
                        <Server size={14} style={{ display: "inline", marginRight: 6 }} /> System Health
                    </h2>
                    <div className="flex flex-col gap-3">
                        {[
                            {
                                label: "Backend API",
                                ok: health?.status === "ok",
                                detail: health?.service ?? "Checking…",
                            },
                            {
                                label: "Google Classroom",
                                ok: classroom?.authenticated ?? false,
                                detail: classroom?.authenticated ? "OAuth active" : "Not connected",
                            },
                            {
                                label: "Code Eval Backend",
                                ok: !!runtime,
                                detail: runtime?.execution_backend ?? "Checking…",
                            },
                            {
                                label: "MicroVM",
                                ok: (runtime?.microvm as Record<string, unknown>)?.enabled !== true,
                                detail: (runtime?.microvm as Record<string, unknown>)?.enabled ? "Enabled" : "Disabled (using local)",
                            },
                        ].map(({ label, ok, detail }) => (
                            <div key={label} style={{
                                display: "flex", alignItems: "center", gap: "var(--space-3)",
                                padding: "var(--space-3)", borderRadius: "var(--radius)",
                                background: "var(--bg-elevated)", border: "1px solid var(--border)",
                            }}>
                                {ok
                                    ? <CheckCircle size={15} style={{ color: "var(--success)", flexShrink: 0 }} />
                                    : <AlertTriangle size={15} style={{ color: "var(--warning)", flexShrink: 0 }} />}
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>{label}</div>
                                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{String(detail)}</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Runtime details */}
                {runtime && (
                    <div className="card">
                        <h2 className="section-title" style={{ marginBottom: "var(--space-4)" }}>Runtime Details</h2>
                        <div className="code-block" style={{ fontSize: 11 }}>
                            {JSON.stringify(runtime, null, 2)}
                        </div>
                    </div>
                )}
            </div>
        </PageShell>
    );
}
