"use client";
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
    Code2, RefreshCw, CheckCircle, XCircle, Clock,
    AlertTriangle, ChevronRight,
} from "lucide-react";
import { PageShell, Sidebar } from "@/components/layout/Shell";
import { api } from "@/lib/api";
import type { JobStatus } from "@/lib/types";

const SIDEBAR_ITEMS = [
    { href: "/code-eval", label: "Overview", icon: Code2 },
    { href: "/code-eval/jobs", label: "Job Monitor", icon: RefreshCw },
    { href: "/code-eval/environments", label: "Environments", icon: Code2 },
];

const STATUS_CLASS: Record<string, string> = {
    QUEUED: "badge-default", EXECUTING_RAW: "badge-info", AI_ANALYZING: "badge-accent",
    RETRYING_SHIM: "badge-warning", FINALIZING: "badge-info",
    COMPLETED: "badge-success", FAILED: "badge-danger",
};

function JobStatusIcon({ status }: { status: JobStatus }) {
    if (status === "COMPLETED") return <CheckCircle size={15} style={{ color: "var(--success)" }} />;
    if (status === "FAILED") return <XCircle size={15} style={{ color: "var(--danger)" }} />;
    if (["QUEUED"].includes(status)) return <Clock size={15} style={{ color: "var(--text-muted)" }} />;
    return <RefreshCw size={15} style={{ color: "var(--accent)", animation: "spin 1.5s linear infinite" }} />;
}

export default function CodeEvalJobsPage() {
    const router = useRouter();
    const [statusFilter, setStatusFilter] = useState<JobStatus | "">("");

    const { data: jobs = [], isLoading, refetch } = useQuery({
        queryKey: ["code-eval-jobs", statusFilter],
        queryFn: () => api.codeEval.jobs.list({ status: statusFilter || undefined }),
        refetchInterval: (q) => {
            const data = q.state.data;
            const hasActive = Array.isArray(data) && data.some(j => !["COMPLETED", "FAILED"].includes(j.status));
            return hasActive ? 3000 : 10_000;
        },
    });

    const { data: runtimeStatus } = useQuery({
        queryKey: ["runtime-status"],
        queryFn: api.codeEval.runtimeStatus,
    });

    const activeCount = jobs.filter(j => !["COMPLETED", "FAILED"].includes(j.status)).length;
    const completedCount = jobs.filter(j => j.status === "COMPLETED").length;
    const failedCount = jobs.filter(j => j.status === "FAILED").length;

    return (
        <PageShell sidebar={<Sidebar items={SIDEBAR_ITEMS} />}>
            {/* Header */}
            <div className="page-header">
                <div>
                    <h1 className="page-title">Code Evaluation Jobs</h1>
                    <p className="page-subtitle">
                        {activeCount > 0
                            ? <span style={{ color: "var(--warning)" }}>{activeCount} running</span>
                            : "All idle"}
                        {" · "}{jobs.length} total
                    </p>
                </div>
                <div className="page-actions">
                    {/* Runtime status chip */}
                    {runtimeStatus && (
                        <div style={{
                            padding: "5px 12px",
                            background: "var(--bg-elevated)",
                            border: "1px solid var(--border-medium)",
                            borderRadius: "var(--radius-full)",
                            fontSize: 12, color: "var(--text-secondary)",
                        }}>
                            Backend: <strong style={{ color: "var(--text-primary)" }}>{runtimeStatus.execution_backend}</strong>
                        </div>
                    )}
                    <button className="btn btn-secondary" onClick={() => refetch()}>
                        <RefreshCw size={13} /> Refresh
                    </button>
                </div>
            </div>

            {/* Stats */}
            <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)", marginBottom: "var(--space-6)" }}>
                <div className="stat-card warning">
                    <div className="stat-label">Active</div>
                    <div className="stat-value">{activeCount}</div>
                </div>
                <div className="stat-card success">
                    <div className="stat-label">Completed</div>
                    <div className="stat-value">{completedCount}</div>
                </div>
                <div className={`stat-card ${failedCount > 0 ? "danger" : "default"}`}>
                    <div className="stat-label">Failed</div>
                    <div className="stat-value">{failedCount}</div>
                </div>
            </div>

            {/* Filter */}
            <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-4)" }}>
                <select className="input" style={{ width: 200 }} value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value as JobStatus | "")}>
                    <option value="">All statuses</option>
                    {["QUEUED", "EXECUTING_RAW", "AI_ANALYZING", "RETRYING_SHIM", "FINALIZING", "COMPLETED", "FAILED"].map(s => (
                        <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                    ))}
                </select>
            </div>

            {/* Jobs table */}
            {isLoading ? (
                <div className="flex flex-col gap-3">
                    {[...Array(5)].map((_, i) => <div key={i} className="skeleton" style={{ height: 56, borderRadius: "var(--radius)" }} />)}
                </div>
            ) : jobs.length === 0 ? (
                <div className="empty-state">
                    <Code2 size={48} className="empty-icon" />
                    <div className="empty-title">No jobs</div>
                    <div className="empty-message">Code evaluation jobs will appear here when assignments are graded.</div>
                </div>
            ) : (
                <div className="card" style={{ padding: 0 }}>
                    <div className="table-wrap">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th style={{ width: 40 }}></th>
                                    <th>Job ID</th>
                                    <th>Language</th>
                                    <th>Status</th>
                                    <th>Attempts</th>
                                    <th>Queued</th>
                                    <th>Finished</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {jobs.map(job => (
                                    <tr
                                        key={job.id}
                                        className="clickable"
                                        onClick={() => router.push(`/code-eval/jobs/${job.id}`)}
                                    >
                                        <td><JobStatusIcon status={job.status} /></td>
                                        <td>
                                            <span className="font-mono text-xs">{job.id.slice(0, 12)}…</span>
                                        </td>
                                        <td>
                                            <span className="badge badge-default">{job.language}</span>
                                        </td>
                                        <td>
                                            <span className={`badge ${STATUS_CLASS[job.status] ?? "badge-default"}`}>
                                                {job.status.replace(/_/g, " ")}
                                            </span>
                                        </td>
                                        <td style={{ textAlign: "center", color: "var(--text-secondary)" }}>{job.attempt_count}</td>
                                        <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                            {new Date(job.queued_at).toLocaleTimeString()}
                                        </td>
                                        <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                            {job.finished_at ? new Date(job.finished_at).toLocaleTimeString() : "—"}
                                        </td>
                                        <td><ChevronRight size={14} style={{ color: "var(--text-muted)" }} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </PageShell>
    );
}
