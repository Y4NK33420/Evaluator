"use client";
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
    BookOpen, FileText, AlertTriangle, CheckCircle,
    Clock, Code2, ArrowRight, RefreshCw
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Assignment, CodeEvalJob, SubmissionStatus } from "@/lib/types";

function StatCard({
    label, value, sub, variant = "default", icon: Icon,
}: { label: string; value: number | string; sub?: string; variant?: string; icon?: React.ComponentType<{ size?: number }> }) {
    return (
        <div className={`stat-card ${variant}`} style={{ animationFillMode: "both" }}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{value}</div>
            {sub && <div className="stat-sub">{sub}</div>}
            {Icon && <div className="stat-icon"><Icon size={48} /></div>}
        </div>
    );
}

function AssignmentRow({ assignment }: { assignment: Assignment }) {
    const router = useRouter();
    return (
        <tr className="clickable" onClick={() => router.push(`/assignments/${assignment.id}`)}>
            <td>
                <div className="font-medium" style={{ color: "var(--text-primary)" }}>{assignment.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{assignment.course_id}</div>
            </td>
            <td>
                <span className={`badge ${assignment.is_published ? "badge-success" : "badge-default"}`}>
                    {assignment.is_published ? "Published" : "Draft"}
                </span>
            </td>
            <td style={{ color: "var(--text-muted)", fontSize: 12 }}>
                {assignment.deadline
                    ? new Date(assignment.deadline).toLocaleDateString()
                    : "—"}
            </td>
            <td>
                <div style={{ fontSize: 12, color: "var(--accent)", display: "flex", alignItems: "center", gap: 4 }}>
                    Open <ArrowRight size={12} />
                </div>
            </td>
        </tr>
    );
}

function JobStatusBadge({ status }: { status: string }) {
    const map: Record<string, string> = {
        QUEUED: "badge-warning", EXECUTING_RAW: "badge-info", AI_ANALYZING: "badge-info",
        RETRYING_SHIM: "badge-warning", FINALIZING: "badge-accent",
        COMPLETED: "badge-success", FAILED: "badge-danger",
    };
    return <span className={`badge ${map[status] ?? "badge-default"}`}>{status.replace(/_/g, " ")}</span>;
}

export default function DashboardPage() {
    const { actor, courseId } = useAuth();
    const router = useRouter();

    const { data: assignments = [], isLoading: aLoading } = useQuery({
        queryKey: ["assignments"],
        queryFn: api.assignments.list,
    });

    const { data: health } = useQuery({
        queryKey: ["health"],
        queryFn: api.health.get,
        refetchInterval: 30_000,
    });

    const { data: jobs = [], isLoading: jLoading } = useQuery({
        queryKey: ["jobs-active"],
        queryFn: () => api.codeEval.jobs.list({}),
        refetchInterval: 5_000,
    });

    const activeJobs = jobs.filter(j => !["COMPLETED", "FAILED"].includes(j.status));
    const failedJobs = jobs.filter(j => j.status === "FAILED");

    const recentAssignments = [...assignments]
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
        .slice(0, 5);

    const totalAssignments = assignments.length;
    const published = assignments.filter(a => a.is_published).length;

    return (
        <PageShell>
            <div className="animate-fade-up">
                {/* Header */}
                <div className="page-header">
                    <div>
                        <h1 className="page-title">
                            Welcome back{actor ? `, ${actor.split(" ")[0]}` : ""}
                        </h1>
                        <p className="page-subtitle">
                            Course <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>{courseId}</span>
                            {" · "}{new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
                        </p>
                    </div>
                    <div className="page-actions">
                        <div className="flex items-center gap-2" style={{
                            padding: "5px 12px",
                            background: health?.status === "ok" ? "var(--success-dim)" : "var(--danger-dim)",
                            border: `1px solid ${health?.status === "ok" ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`,
                            borderRadius: "var(--radius-full)",
                            fontSize: 12, color: health?.status === "ok" ? "var(--success)" : "var(--danger)",
                        }}>
                            <div style={{
                                width: 7, height: 7, borderRadius: "50%",
                                background: health?.status === "ok" ? "var(--success)" : "var(--danger)",
                                animation: health?.status === "ok" ? "pulse 2s infinite" : "none",
                            }} />
                            {health?.status === "ok" ? "Backend Online" : "Backend Offline"}
                        </div>
                        <button
                            className="btn btn-primary"
                            onClick={() => router.push("/assignments/new")}
                        >
                            <BookOpen size={14} /> New Assignment
                        </button>
                    </div>
                </div>

                {/* Stat cards */}
                <div className="stat-grid">
                    <StatCard
                        label="Assignments"
                        value={aLoading ? "—" : totalAssignments}
                        sub={`${published} published`}
                        variant="accent"
                        icon={BookOpen}
                    />
                    <StatCard
                        label="Active Jobs"
                        value={jLoading ? "—" : activeJobs.length}
                        sub={activeJobs.length > 0 ? "Running now" : "All idle"}
                        variant={activeJobs.length > 0 ? "warning" : "default"}
                        icon={RefreshCw}
                    />
                    <StatCard
                        label="Failed Jobs"
                        value={jLoading ? "—" : failedJobs.length}
                        sub={failedJobs.length > 0 ? "Needs attention" : "Everything OK"}
                        variant={failedJobs.length > 0 ? "danger" : "default"}
                        icon={AlertTriangle}
                    />
                    <StatCard
                        label="Published"
                        value={aLoading ? "—" : published}
                        sub={`of ${totalAssignments} assignments`}
                        variant="success"
                        icon={CheckCircle}
                    />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: "var(--space-6)" }}>
                    {/* Recent assignments */}
                    <div>
                        <div className="section-header">
                            <h2 className="section-title">Recent Assignments</h2>
                            <button className="btn btn-ghost btn-sm" onClick={() => router.push("/assignments")}>
                                View all <ArrowRight size={12} />
                            </button>
                        </div>
                        <div className="card" style={{ padding: 0 }}>
                            {aLoading ? (
                                <div style={{ padding: "var(--space-6)" }}>
                                    {[...Array(4)].map((_, i) => (
                                        <div key={i} className="skeleton" style={{ height: 40, marginBottom: 12, borderRadius: "var(--radius)" }} />
                                    ))}
                                </div>
                            ) : recentAssignments.length === 0 ? (
                                <div className="empty-state" style={{ padding: "var(--space-10)" }}>
                                    <BookOpen size={36} className="empty-icon" />
                                    <div className="empty-title">No assignments yet</div>
                                    <div className="empty-message">Create your first assignment to get started.</div>
                                    <button className="btn btn-primary btn-sm" onClick={() => router.push("/assignments/new")}>
                                        Create Assignment
                                    </button>
                                </div>
                            ) : (
                                <div className="table-wrap">
                                    <table className="data-table">
                                        <thead>
                                            <tr>
                                                <th>Assignment</th>
                                                <th>Status</th>
                                                <th>Deadline</th>
                                                <th></th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {recentAssignments.map(a => <AssignmentRow key={a.id} assignment={a} />)}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Active jobs sidebar */}
                    <div>
                        <div className="section-header">
                            <h2 className="section-title">Active Jobs</h2>
                            <button className="btn btn-ghost btn-sm" onClick={() => router.push("/code-eval/jobs")}>
                                View all <ArrowRight size={12} />
                            </button>
                        </div>
                        <div className="card" style={{ padding: 0 }}>
                            {jLoading ? (
                                <div style={{ padding: "var(--space-4)" }}>
                                    {[...Array(3)].map((_, i) => (
                                        <div key={i} className="skeleton" style={{ height: 56, marginBottom: 8, borderRadius: "var(--radius)" }} />
                                    ))}
                                </div>
                            ) : activeJobs.length === 0 ? (
                                <div className="empty-state" style={{ padding: "var(--space-8)" }}>
                                    <Code2 size={28} className="empty-icon" />
                                    <div className="empty-title">No active jobs</div>
                                    <div className="empty-message" style={{ fontSize: 11 }}>Code evaluation jobs will appear here.</div>
                                </div>
                            ) : (
                                <div style={{ padding: "var(--space-3)" }}>
                                    {activeJobs.slice(0, 6).map(job => (
                                        <div key={job.id} style={{
                                            padding: "var(--space-3)",
                                            borderRadius: "var(--radius)",
                                            display: "flex", flexDirection: "column", gap: 4,
                                            borderBottom: "1px solid var(--border)",
                                        }}>
                                            <div className="flex items-center justify-between">
                                                <span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                                                    {job.id.slice(0, 8)}…
                                                </span>
                                                <JobStatusBadge status={job.status} />
                                            </div>
                                            <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                                                {job.language} · {job.entrypoint}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Quick actions */}
                        <div style={{ marginTop: "var(--space-4)" }}>
                            <div className="section-title" style={{ marginBottom: "var(--space-3)" }}>Quick Actions</div>
                            <div className="flex flex-col gap-2">
                                {[
                                    { label: "Upload Submissions", icon: FileText, href: "/submissions" },
                                    { label: "View All Assignments", icon: BookOpen, href: "/assignments" },
                                    { label: "Code Eval Monitor", icon: Code2, href: "/code-eval/jobs" },
                                    { label: "System Health", icon: CheckCircle, href: "/settings/system" },
                                ].map(({ label, icon: Icon, href }) => (
                                    <button
                                        key={href}
                                        className="btn btn-secondary"
                                        style={{ justifyContent: "flex-start", width: "100%" }}
                                        onClick={() => router.push(href)}
                                    >
                                        <Icon size={14} style={{ opacity: 0.6 }} />
                                        {label}
                                        <ArrowRight size={12} style={{ marginLeft: "auto", opacity: 0.4 }} />
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
        </PageShell>
    );
}
