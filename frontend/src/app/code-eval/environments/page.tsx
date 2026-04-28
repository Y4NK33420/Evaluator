"use client";
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
    Plus, RefreshCw, CheckCircle, XCircle, Clock, AlertTriangle,
    ChevronRight, Hammer, Eye, Code2, Server, GitBranch,
} from "lucide-react";
import { PageShell, Sidebar } from "@/components/layout/Shell";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { EnvStatus, EnvironmentVersion } from "@/lib/types";

const SIDEBAR_ITEMS = [
    { href: "/code-eval", label: "Overview", icon: Code2 },
    { href: "/code-eval/jobs", label: "Job Monitor", icon: RefreshCw },
    { href: "/code-eval/environments", label: "Environments", icon: Server },
];

const STATUS_CLASS: Record<EnvStatus, string> = {
    draft: "badge-default", building: "badge-warning",
    ready: "badge-success", failed: "badge-danger", deprecated: "badge-muted",
};

const STATUS_ICON: Record<EnvStatus, React.ReactNode> = {
    draft: <Clock size={14} style={{ color: "var(--text-muted)" }} />,
    building: <RefreshCw size={14} style={{ color: "var(--warning)", animation: "spin 1.5s linear infinite" }} />,
    ready: <CheckCircle size={14} style={{ color: "var(--success)" }} />,
    failed: <XCircle size={14} style={{ color: "var(--danger)" }} />,
    deprecated: <AlertTriangle size={14} style={{ color: "var(--text-muted)" }} />,
};

const PROFILE_DESCRIPTIONS: Record<string, string> = {
    "python-3.11": "Python 3.11 sandbox with standard data-science libs",
    "python-3.10": "Python 3.10 sandbox",
    "node-18": "Node.js 18 LTS sandbox",
    "java-17": "OpenJDK 17 sandbox",
    "cpp-17": "GCC 12 C++17 sandbox",
    custom: "Custom environment defined via spec_json",
};

const PROFILE_KEYS = ["python-3.11", "python-3.10", "node-18", "java-17", "cpp-17", "custom"];

// ── Create Environment drawer ──────────────────────────────────────────────────
function CreateEnvDrawer({
    open, onClose, courseId,
}: { open: boolean; onClose: () => void; courseId: string; }) {
    const qc = useQueryClient();
    const { actor } = useAuth();
    const { toast } = useToast();

    const [profileKey, setProfileKey] = useState("python-3.11");
    const [reuseMode, setReuseMode] = useState("course_reuse_with_assignment_overrides");
    const [specJson, setSpecJson] = useState("{}");
    const [specError, setSpecError] = useState<string | null>(null);

    const createMutation = useMutation({
        mutationFn: () => {
            let spec: Record<string, unknown>;
            try { spec = JSON.parse(specJson); } catch { throw new Error("spec_json is not valid JSON"); }
            return api.codeEval.environments.create({
                course_id: courseId,
                profile_key: profileKey,
                reuse_mode: reuseMode,
                spec_json: spec,
                created_by: actor ?? "instructor",
            });
        },
        onSuccess: () => {
            toast("success", "Environment created", "You can now trigger a build.");
            qc.invalidateQueries({ queryKey: ["environments"] });
            onClose();
            setSpecJson("{}");
        },
        onError: (e: Error) => toast("error", "Create failed", e.message),
    });

    const validateSpec = (v: string) => {
        try { JSON.parse(v); setSpecError(null); } catch { setSpecError("Invalid JSON"); }
        setSpecJson(v);
    };

    if (!open) return null;

    return (
        <div style={{
            position: "fixed", inset: 0, zIndex: 200,
            display: "flex", justifyContent: "flex-end",
        }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.5)" }} onClick={onClose} />
            <div style={{
                position: "relative", width: 440, background: "var(--bg-card)",
                borderLeft: "1px solid var(--border-medium)", padding: "var(--space-6)",
                overflow: "auto", display: "flex", flexDirection: "column", gap: "var(--space-4)",
            }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>New Environment Version</h2>

                <div className="input-group">
                    <label className="input-label">Profile Key</label>
                    <select className="input" value={profileKey} onChange={e => setProfileKey(e.target.value)}>
                        {PROFILE_KEYS.map(k => <option key={k} value={k}>{k}</option>)}
                    </select>
                    <span className="input-hint">{PROFILE_DESCRIPTIONS[profileKey]}</span>
                </div>

                <div className="input-group">
                    <label className="input-label">Reuse Mode</label>
                    <select className="input" value={reuseMode} onChange={e => setReuseMode(e.target.value)}>
                        <option value="course_reuse_with_assignment_overrides">Course-wide (with per-assignment overrides)</option>
                        <option value="assignment_only">Assignment only</option>
                    </select>
                </div>

                <div className="input-group">
                    <label className="input-label">spec_json</label>
                    <textarea
                        className={`input ${specError ? "input-error" : ""}`}
                        rows={8}
                        value={specJson}
                        onChange={e => validateSpec(e.target.value)}
                        style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
                        placeholder={'{\n  "mode": "manifest",\n  "image_reference": "ghcr.io/..."\n}'}
                    />
                    {specError && <span className="input-hint" style={{ color: "var(--danger)" }}>{specError}</span>}
                    <span className="input-hint">
                        Supported keys: mode, image_reference, snapshot_vmstate_path, snapshot_mem_path,
                        microvm_policy, and any custom overrides.
                    </span>
                </div>

                <div className="flex items-center gap-3" style={{ marginTop: "auto" }}>
                    <button className="btn btn-secondary flex-1" onClick={onClose}>Cancel</button>
                    <button
                        className="btn btn-primary flex-1"
                        onClick={() => createMutation.mutate()}
                        disabled={createMutation.isPending || !!specError}
                    >
                        {createMutation.isPending ? "Creating…" : "Create"}
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Environment detail popover ─────────────────────────────────────────────────
function EnvDetailModal({ env, onClose, onBuildTriggered }: {
    env: EnvironmentVersion;
    onClose: () => void;
    onBuildTriggered: () => void;
}) {
    const qc = useQueryClient();
    const { actor } = useAuth();
    const { toast } = useToast();
    const [buildConfirm, setBuildConfirm] = useState(false);
    const [forceRebuild, setForceRebuild] = useState(false);

    const buildMutation = useMutation({
        mutationFn: (force: boolean) => api.codeEval.environments.build(env.id, actor ?? "instructor", force),
        onSuccess: () => {
            toast("success", "Build triggered", "Check the build logs for progress.");
            qc.invalidateQueries({ queryKey: ["environments"] });
            setBuildConfirm(false);
            onBuildTriggered();
        },
        onError: (e: Error) => toast("error", "Build failed", e.message),
    });

    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)" }} onClick={onClose} />
            <div style={{
                position: "relative", width: 600, maxHeight: "85vh",
                background: "var(--bg-card)", borderRadius: "var(--radius-lg)",
                border: "1px solid var(--border-medium)", overflow: "auto",
                display: "flex", flexDirection: "column",
            }}>
                {/* Header */}
                <div style={{ padding: "var(--space-4) var(--space-6)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div className="flex items-center gap-3">
                        <span>{STATUS_ICON[env.status]}</span>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{env.profile_key}</div>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>v{env.version_number} · {env.id.slice(0, 12)}…</div>
                        </div>
                        <span className={`badge ${STATUS_CLASS[env.status]}`}>{env.status}</span>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={onClose}><XCircle size={14} /></button>
                </div>

                {/* Body */}
                <div style={{ padding: "var(--space-6)", flex: 1 }}>
                    {/* Labels */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)", marginBottom: "var(--space-4)" }}>
                        {[
                            { label: "Reuse Mode", value: env.reuse_mode.replace(/_/g, " ") },
                            { label: "Is Active", value: env.is_active ? "Yes" : "No" },
                            { label: "Freeze Key", value: env.freeze_key ?? "Not frozen" },
                            { label: "Created By", value: env.created_by ?? "—" },
                        ].map(({ label, value }) => (
                            <div key={label} style={{ padding: "var(--space-3)", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>{label}</div>
                                <div style={{ fontSize: 12, color: "var(--text-primary)", fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>{value}</div>
                            </div>
                        ))}
                    </div>

                    {/* spec_json */}
                    <div style={{ marginBottom: "var(--space-4)" }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: "var(--space-2)", textTransform: "uppercase", letterSpacing: "0.05em" }}>spec_json</div>
                        <pre style={{ background: "var(--bg-base)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", padding: "var(--space-3)", margin: 0, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", overflow: "auto", maxHeight: 200 }}>
                            {JSON.stringify(env.spec_json, null, 2)}
                        </pre>
                    </div>

                    {/* Build logs */}
                    {env.build_logs && (
                        <div style={{ marginBottom: "var(--space-4)" }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: "var(--space-2)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Build Logs</div>
                            <pre style={{ background: "var(--bg-base)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", padding: "var(--space-3)", margin: 0, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", overflow: "auto", maxHeight: 200, whiteSpace: "pre-wrap" }}>
                                {env.build_logs}
                            </pre>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div style={{ padding: "var(--space-4) var(--space-6)", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <label className="flex items-center gap-2" style={{ fontSize: 13, cursor: "pointer" }}>
                        <input type="checkbox" checked={forceRebuild} onChange={e => setForceRebuild(e.target.checked)} />
                        Force rebuild (clear freeze key)
                    </label>
                    <button
                        className="btn btn-primary"
                        onClick={() => setBuildConfirm(true)}
                        disabled={env.status === "building"}
                    >
                        <Hammer size={13} /> {env.status === "building" ? "Building…" : "Trigger Build"}
                    </button>
                </div>
            </div>

            <ConfirmModal
                open={buildConfirm}
                title={forceRebuild ? "Force Rebuild Environment" : "Trigger Build"}
                message={forceRebuild
                    ? "This will clear the freeze key and rebuild from scratch. Active jobs on this environment may be affected."
                    : "Trigger a build or freeze for this environment version. This runs as a background task."}
                confirmText="Build"
                onConfirm={() => buildMutation.mutate(forceRebuild)}
                onCancel={() => setBuildConfirm(false)}
                loading={buildMutation.isPending}
                variant={forceRebuild ? "danger" : "default"}
            />
        </div>
    );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function EnvironmentsPage() {
    const { courseId } = useAuth();
    const router = useRouter();
    const [showCreate, setShowCreate] = useState(false);
    const [selected, setSelected] = useState<EnvironmentVersion | null>(null);
    const [statusFilter, setStatusFilter] = useState<string>("");

    const { data: envs = [], isLoading, refetch } = useQuery({
        queryKey: ["environments", courseId, statusFilter],
        queryFn: () => api.codeEval.environments.list({ course_id: courseId ?? undefined, status: statusFilter || undefined }),
        refetchInterval: (q) => {
            const hasBuilding = Array.isArray(q.state.data) && q.state.data.some(e => e.status === "building");
            return hasBuilding ? 3000 : 15_000;
        },
    });

    const buildingCount = envs.filter(e => e.status === "building").length;
    const readyCount = envs.filter(e => e.status === "ready").length;
    const failedCount = envs.filter(e => e.status === "failed").length;

    return (
        <PageShell sidebar={<Sidebar items={SIDEBAR_ITEMS} />}>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Code Eval Environments</h1>
                    <p className="page-subtitle">
                        {buildingCount > 0
                            ? <span style={{ color: "var(--warning)" }}>{buildingCount} building</span>
                            : `${readyCount} ready`} · {envs.length} total
                    </p>
                </div>
                <div className="page-actions">
                    <button className="btn btn-secondary" onClick={() => refetch()}>
                        <RefreshCw size={13} /> Refresh
                    </button>
                    <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                        <Plus size={13} /> New Environment
                    </button>
                </div>
            </div>

            {/* Stat strip */}
            <div className="stat-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "var(--space-6)" }}>
                {[
                    { label: "Ready", value: readyCount, cls: "success" },
                    { label: "Building", value: buildingCount, cls: "warning" },
                    { label: "Failed", value: failedCount, cls: failedCount > 0 ? "danger" : "default" },
                    { label: "Total", value: envs.length, cls: "default" },
                ].map(({ label, value, cls }) => (
                    <div key={label} className={`stat-card ${cls}`}>
                        <div className="stat-label">{label}</div>
                        <div className="stat-value">{value}</div>
                    </div>
                ))}
            </div>

            {/* Filter row */}
            <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-4)" }}>
                <select className="input" style={{ width: 200 }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                    <option value="">All statuses</option>
                    {["draft", "building", "ready", "failed", "deprecated"].map(s => (
                        <option key={s} value={s}>{s}</option>
                    ))}
                </select>
            </div>

            {/* Env grid */}
            {isLoading ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "var(--space-4)" }}>
                    {[...Array(6)].map((_, i) => <div key={i} className="skeleton" style={{ height: 140, borderRadius: "var(--radius-lg)" }} />)}
                </div>
            ) : envs.length === 0 ? (
                <div className="empty-state">
                    <Server size={48} className="empty-icon" />
                    <div className="empty-title">No environments yet</div>
                    <div className="empty-message">Create an environment to enable code evaluation for your assignments.</div>
                    <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                        <Plus size={13} /> Create First Environment
                    </button>
                </div>
            ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "var(--space-4)" }}>
                    {envs.map(env => (
                        <div
                            key={env.id}
                            className="card"
                            style={{
                                cursor: "pointer", transition: "border-color 0.15s, transform 0.15s",
                                borderColor: env.status === "building" ? "rgba(245,158,11,0.4)" : undefined,
                            }}
                            onClick={() => setSelected(env)}
                            onMouseEnter={e => (e.currentTarget.style.transform = "translateY(-2px)")}
                            onMouseLeave={e => (e.currentTarget.style.transform = "")}
                        >
                            <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-3)" }}>
                                <div className="flex items-center gap-2">
                                    {STATUS_ICON[env.status]}
                                    <span style={{ fontWeight: 600, fontSize: 14, color: "var(--text-primary)" }}>{env.profile_key}</span>
                                </div>
                                <span className={`badge ${STATUS_CLASS[env.status]}`}>{env.status}</span>
                            </div>

                            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginBottom: "var(--space-3)" }}>
                                <span className="badge badge-default">v{env.version_number}</span>
                                <span className="badge badge-default">{env.reuse_mode === "assignment_only" ? "Assignment only" : "Course-wide"}</span>
                                {env.freeze_key && <span className="badge badge-info">Frozen</span>}
                                {!env.is_active && <span className="badge badge-muted">Inactive</span>}
                            </div>

                            <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", justifyContent: "space-between" }}>
                                <span>{new Date(env.created_at).toLocaleDateString()}</span>
                                <span style={{ fontFamily: "var(--font-mono)" }}>{env.id.slice(0, 12)}…</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Create drawer */}
            <CreateEnvDrawer
                open={showCreate}
                onClose={() => setShowCreate(false)}
                courseId={courseId ?? ""}
            />

            {/* Detail modal */}
            {selected && (
                <EnvDetailModal
                    env={selected}
                    onClose={() => setSelected(null)}
                    onBuildTriggered={() => setSelected(null)}
                />
            )}

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </PageShell>
    );
}
