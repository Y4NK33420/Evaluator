"use client";
import React, { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeft, BookOpen, FileText, Code2, Globe, CheckCircle,
    XCircle, AlertTriangle, Download, RefreshCw, Send, Upload,
    Sparkles, ChevronDown, ChevronRight, Edit3, Eye,
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Assignment, Rubric, PublishValidation, SyncSummary, Submission } from "@/lib/types";

// ── Sub-components ─────────────────────────────────────────────────────────

function StatusBadge({ published }: { published: boolean }) {
    return (
        <span className={`badge ${published ? "badge-success" : "badge-default"}`} style={{ fontSize: 12, padding: "3px 10px" }}>
            {published ? "Published" : "Draft"}
        </span>
    );
}

function CheckRow({ name, ok }: { name: string; ok: boolean }) {
    return (
        <div className="flex items-center gap-3" style={{
            padding: "var(--space-2) var(--space-3)",
            borderRadius: "var(--radius-sm)",
            background: ok ? "var(--success-dim)" : "var(--danger-dim)",
        }}>
            {ok
                ? <CheckCircle size={14} style={{ color: "var(--success)", flexShrink: 0 }} />
                : <XCircle size={14} style={{ color: "var(--danger)", flexShrink: 0 }} />}
            <span style={{ flex: 1, fontSize: 12, color: ok ? "var(--text-secondary)" : "var(--text-primary)" }}>
                {name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
            </span>
            <span style={{ fontSize: 11, color: ok ? "var(--success)" : "var(--danger)" }}>
                {ok ? "Pass" : "Fail"}
            </span>
        </div>
    );
}

// ── Overview Tab ─────────────────────────────────────────────────────────

function OverviewTab({ assignment, rubric, validation, onPublish, publishing, onSwitchTab }: {
    assignment: Assignment;
    rubric: Rubric | null;
    validation: PublishValidation | null;
    onPublish: () => void;
    publishing: boolean;
    onSwitchTab: (tab: string) => void;
}) {
    const router = useRouter();
    return (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "var(--space-6)" }}>
            {/* Left: details */}
            <div className="flex flex-col gap-6">
                <div className="card">
                    <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>Assignment Info</h3>
                    <div className="flex flex-col gap-3">
                        {[
                            { label: "Course ID", value: assignment.course_id },
                            { label: "Max Marks", value: `${assignment.max_marks}` },
                            { label: "Type", value: assignment.has_code_question ? "Coding + Rubric" : assignment.question_type.charAt(0).toUpperCase() + assignment.question_type.slice(1) },
                            { label: "Deadline", value: assignment.deadline ? new Date(assignment.deadline).toLocaleString() : "No deadline" },
                            { label: "Created", value: new Date(assignment.created_at).toLocaleDateString() },
                            { label: "Classroom ID", value: assignment.classroom_id || "Not linked" },
                        ].map(({ label, value }) => (
                            <div key={label} style={{ display: "flex", gap: "var(--space-4)", paddingBottom: "var(--space-2)", borderBottom: "1px solid var(--border)" }}>
                                <div style={{ width: 110, flexShrink: 0, fontSize: 12, color: "var(--text-muted)", fontWeight: 500 }}>{label}</div>
                                <div style={{ fontSize: 13, color: "var(--text-primary)", fontFamily: label === "Classroom ID" || label === "Course ID" ? "var(--font-mono)" : undefined }}>{value}</div>
                            </div>
                        ))}
                    </div>
                    {assignment.description && (
                        <div style={{ marginTop: "var(--space-4)", padding: "var(--space-3)", background: "var(--bg-elevated)", borderRadius: "var(--radius)", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7 }}>
                            {assignment.description}
                        </div>
                    )}
                </div>

                {/* Rubric summary */}
                <div className="card">
                    <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-4)" }}>
                        <h3 className="section-title">Rubric</h3>
                        <button className="btn btn-ghost btn-sm" onClick={() => onSwitchTab("rubric")}>
                            <Eye size={13} /> View Rubric Tab
                        </button>
                    </div>
                    {!rubric ? (
                        <div style={{
                            padding: "var(--space-4)", borderRadius: "var(--radius)",
                            background: "var(--warning-dim)", border: "1px solid rgba(245,158,11,0.25)",
                            display: "flex", alignItems: "center", gap: "var(--space-3)",
                        }}>
                            <AlertTriangle size={14} style={{ color: "var(--warning)", flexShrink: 0 }} />
                            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                                No rubric yet. Create or generate one in the Rubric tab before publishing.
                            </div>
                        </div>
                    ) : (
                        <div className="flex items-center gap-3">
                            <span className={`badge ${rubric.approved ? "badge-success" : "badge-warning"}`}>
                                {rubric.approved ? "Approved" : "Pending Approval"}
                            </span>
                            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                {rubric.source === "ai_generated" ? "AI Generated" : "Manual"}
                            </span>
                            {rubric.approved_by && (
                                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                    by {rubric.approved_by}
                                </span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Right: publish */}
            <div className="flex flex-col gap-4">
                <div className="card">
                    <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>Publish Status</h3>
                    <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-4)" }}>
                        <StatusBadge published={assignment.is_published} />
                        {assignment.published_by && (
                            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>by {assignment.published_by}</span>
                        )}
                    </div>

                    {validation && (
                        <div className="flex flex-col gap-2" style={{ marginBottom: "var(--space-4)" }}>
                            {Object.entries(validation.checks).map(([k, v]) => (
                                <CheckRow key={k} name={k} ok={v} />
                            ))}
                        </div>
                    )}

                    <button
                        className={`btn w-full ${validation?.ready_for_publish ? "btn-primary" : "btn-secondary"}`}
                        onClick={onPublish}
                        disabled={publishing || !validation?.ready_for_publish && !assignment.is_published}
                    >
                        {publishing ? <><RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> Publishing…</> : (
                            assignment.is_published
                                ? <><RefreshCw size={13} /> Republish</>
                                : <><Send size={13} /> Publish Assignment</>
                        )}
                    </button>

                    {!validation?.ready_for_publish && validation?.missing.length && (
                        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: "var(--space-3)", textAlign: "center" }}>
                            Fix {validation.missing.length} issue{validation.missing.length > 1 ? "s" : ""} to publish
                        </div>
                    )}
                </div>

                {/* Quick actions */}
                <div className="card">
                    <h3 className="section-title" style={{ marginBottom: "var(--space-3)" }}>Actions</h3>
                    <div className="flex flex-col gap-2">
                        <a className="btn btn-secondary" style={{ justifyContent: "flex-start" }}
                            href={api.assignments.gradesCSVUrl(assignment.id)} target="_blank" rel="noreferrer">
                            <Download size={13} /> Download Grade CSV
                        </a>
                        <button className="btn btn-secondary" style={{ justifyContent: "flex-start" }}
                            onClick={() => router.push(`/submissions?assignmentId=${assignment.id}`)}>
                            <Upload size={13} /> Upload Submissions
                        </button>
                        <button className="btn btn-secondary" style={{ justifyContent: "flex-start" }}
                            onClick={() => router.push(`/submissions?assignmentId=${assignment.id}`)}>
                            <FileText size={13} /> View Submissions
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── Rubric Tab ─────────────────────────────────────────────────────────────

function RubricTab({ assignment, rubric, onRefresh }: {
    assignment: Assignment;
    rubric: Rubric | null;
    onRefresh: () => void;
}) {
    const { actor } = useAuth();
    const { toast } = useToast();
    const [masterAnswer, setMasterAnswer] = useState("");
    const [generating, setGenerating] = useState(false);
    const [showRaw, setShowRaw] = useState(false);

    const approveMutation = useMutation({
        mutationFn: () => api.rubrics.approve(rubric!.id, actor ?? "ta"),
        onSuccess: () => { toast("success", "Rubric approved!"); onRefresh(); },
        onError: (e: Error) => toast("error", "Approval failed", e.message),
    });

    const generateRubric = async () => {
        if (!masterAnswer.trim()) { toast("warning", "Enter a master answer first"); return; }
        setGenerating(true);
        try {
            await api.rubrics.generate(assignment.id, masterAnswer);
            toast("success", "Rubric generated!", "Review and approve it below.");
            onRefresh();
        } catch (e: unknown) {
            toast("error", "Generation failed", (e as Error).message);
        } finally {
            setGenerating(false);
        }
    };

    const questions = rubric?.content_json?.questions ?? [];

    return (
        <div className="flex flex-col gap-6">
            {/* Generate section */}
            <div className="card">
                <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>
                    <Sparkles size={14} style={{ display: "inline", marginRight: 6, color: "var(--accent)" }} />
                    AI Rubric Generation
                </h3>
                <div className="input-group">
                    <label className="input-label">Master Answer / Solution</label>
                    <textarea
                        className="input"
                        rows={5}
                        placeholder="Paste the ideal full answer or solution here. The AI will generate a marking scheme from it…"
                        value={masterAnswer}
                        onChange={e => setMasterAnswer(e.target.value)}
                    />
                    <span className="input-hint">The rubric will require your approval before grading can start.</span>
                </div>
                <button
                    className="btn btn-primary"
                    style={{ marginTop: "var(--space-4)" }}
                    onClick={generateRubric}
                    disabled={generating || !masterAnswer.trim()}
                >
                    {generating
                        ? <><RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> Generating…</>
                        : <><Sparkles size={13} /> Generate Rubric</>}
                </button>
            </div>

            {/* Current rubric */}
            {rubric && (
                <div className="card">
                    <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-4)" }}>
                        <div className="flex items-center gap-3">
                            <h3 className="section-title">Current Rubric</h3>
                            <span className={`badge ${rubric.approved ? "badge-success" : "badge-warning"}`}>
                                {rubric.approved ? "✓ Approved" : "Awaiting Approval"}
                            </span>
                            <span className="badge badge-default">
                                {rubric.source === "ai_generated" ? "AI" : "Manual"}
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <button className="btn btn-ghost btn-sm" onClick={() => setShowRaw(!showRaw)}>
                                {showRaw ? <><Eye size={12} /> Formatted</> : <><Edit3 size={12} /> Raw JSON</>}
                            </button>
                            {!rubric.approved && (
                                <button
                                    className="btn btn-success"
                                    onClick={() => approveMutation.mutate()}
                                    disabled={approveMutation.isPending}
                                >
                                    <CheckCircle size={13} /> Approve Rubric
                                </button>
                            )}
                        </div>
                    </div>

                    {showRaw ? (
                        <div className="code-block" style={{ maxHeight: 400, overflow: "auto" }}>
                            {JSON.stringify(rubric.content_json, null, 2)}
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {questions.length > 0 ? questions.map((q: Record<string, unknown>, i: number) => (
                                <div key={i} style={{
                                    padding: "var(--space-3) var(--space-4)",
                                    borderRadius: "var(--radius)",
                                    background: "var(--bg-elevated)",
                                    border: "1px solid var(--border)",
                                    display: "flex", gap: "var(--space-4)", alignItems: "flex-start",
                                }}>
                                    <div style={{
                                        minWidth: 32, height: 32, borderRadius: "var(--radius-sm)",
                                        background: "var(--accent-dim)", display: "flex", alignItems: "center",
                                        justifyContent: "center", fontSize: 12, fontWeight: 600, color: "var(--accent)", flexShrink: 0,
                                    }}>Q{i + 1}</div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: 13, color: "var(--text-primary)", marginBottom: 2 }}>
                                            {String(q.name ?? q.id ?? `Question ${i + 1}`)}
                                        </div>
                                        {Boolean(q.criteria) && (
                                            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{String(q.criteria)}</div>
                                        )}
                                    </div>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", flexShrink: 0 }}>
                                        {String(q.marks ?? q.max_marks ?? "?")} marks
                                    </div>
                                </div>
                            )) : (
                                <div style={{ fontSize: 13, color: "var(--text-muted)", textAlign: "center", padding: "var(--space-6)" }}>
                                    Rubric content is in a custom format — use Raw JSON to view.
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {!rubric && (
                <div className="empty-state">
                    <BookOpen size={40} className="empty-icon" />
                    <div className="empty-title">No rubric yet</div>
                    <div className="empty-message">Generate one above, or upload a manual rubric via the API.</div>
                </div>
            )}
        </div>
    );
}

// ── Submissions Tab ─────────────────────────────────────────────────

const SUB_STATUS_CLASS: Record<string, string> = {
    pending: "badge-default", processing: "badge-warning",
    ocr_done: "badge-info", grading: "badge-accent",
    graded: "badge-success", failed: "badge-danger",
};

function SubmissionsTab({ assignmentId }: { assignmentId: string }) {
    const router = useRouter();
    const { data: subs = [], isLoading, refetch } = useQuery({
        queryKey: ["submissions-tab", assignmentId],
        queryFn: () => api.submissions.listByAssignment(assignmentId),
        refetchInterval: (q) => {
            const d = q.state.data as Submission[] | undefined;
            const hasActive = Array.isArray(d) && d.some(s => ["pending", "processing", "grading"].includes(s.status));
            return hasActive ? 3000 : false;
        },
    });

    const graded = subs.filter(s => s.status === "graded").length;
    const failed = subs.filter(s => s.status === "failed").length;
    const pending = subs.filter(s => ["pending", "processing", "grading", "ocr_done"].includes(s.status)).length;

    return (
        <div className="flex flex-col gap-4">
            {/* mini stat strip */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-3)" }}>
                {[
                    { label: "Total", value: subs.length, cls: "default" },
                    { label: "Graded", value: graded, cls: "success" },
                    { label: "Pending", value: pending, cls: "warning" },
                    { label: "Failed", value: failed, cls: failed > 0 ? "danger" : "default" },
                ].map(({ label, value, cls }) => (
                    <div key={label} className={`stat-card ${cls}`} style={{ padding: "var(--space-3)" }}>
                        <div className="stat-label">{label}</div>
                        <div className="stat-value" style={{ fontSize: 22 }}>{value}</div>
                    </div>
                ))}
            </div>

            <div className="card" style={{ padding: 0 }}>
                <div style={{ padding: "var(--space-3) var(--space-4)", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>Submissions</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => refetch()}>
                        <RefreshCw size={12} /> Refresh
                    </button>
                </div>

                {isLoading ? (
                    <div className="flex flex-col gap-3" style={{ padding: "var(--space-4)" }}>
                        {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 44, borderRadius: "var(--radius)" }} />)}
                    </div>
                ) : subs.length === 0 ? (
                    <div className="empty-state" style={{ minHeight: 120 }}>
                        <FileText size={32} className="empty-icon" />
                        <div className="empty-title">No submissions yet</div>
                        <div className="empty-message">Upload submissions from the Submissions hub.</div>
                    </div>
                ) : (
                    <div className="table-wrap">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>Student</th>
                                    <th>Status</th>
                                    <th>Score</th>
                                    <th>Uploaded</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {subs.map(sub => (
                                    <tr key={sub.id} className="clickable" onClick={() => router.push(`/submissions/${sub.id}`)}>
                                        <td>
                                            <div style={{ fontWeight: 500, fontSize: 13 }}>{sub.student_name || sub.student_id}</div>
                                            <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{sub.student_id}</div>
                                        </td>
                                        <td><span className={`badge ${SUB_STATUS_CLASS[sub.status]}`}>{sub.status.replace(/_/g, " ")}</span></td>
                                        <td style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                                            {sub.status === "graded" ? "—" : "—"}
                                        </td>
                                        <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                            {new Date(sub.created_at).toLocaleDateString()}
                                        </td>
                                        <td><ChevronRight size={14} style={{ color: "var(--text-muted)" }} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}


// ── Classroom Tab ───────────────────────────────────────────────

// ── ClassroomSyncSummaryWithRows extends SyncSummary with submission rows
type ClassroomStatus = SyncSummary & {
    total_submissions: number;
    graded: number;
    ungraded: number;
    submissions: Array<{
        submission_id: string;
        student_id: string;
        student_name: string | null;
        status: string;
        graded: boolean;
        total_score: number | null;
        grade_source: string | null;
    }>;
};

function ClassroomTab({ assignment }: { assignment: Assignment }) {
    const { toast } = useToast();
    const { data: status } = useQuery({
        queryKey: ["classroom-status", assignment.id],
        queryFn: () => api.classroom.status(assignment.id) as Promise<ClassroomStatus>,
    });
    const { data: authStatus } = useQuery({
        queryKey: ["classroom-auth"],
        queryFn: api.classroom.authStatus,
    });

    const ingest = useMutation({
        mutationFn: () => api.classroom.ingest(assignment.id, {
            course_id: assignment.course_id,
            coursework_id: assignment.classroom_id ?? "",
        }),
        onSuccess: (s) => toast("success", "Ingested!", `${s.ingested} new submissions`),
        onError: (e: Error) => toast("error", "Ingest failed", e.message),
    });
    const syncDraft = useMutation({
        mutationFn: () => api.classroom.syncDraft(assignment.id),
        onSuccess: (s) => toast("success", "Draft synced", `${s.pushed} grades pushed`),
        onError: (e: Error) => toast("error", "Sync failed", e.message),
    });
    const release = useMutation({
        mutationFn: () => api.classroom.release(assignment.id),
        onSuccess: (s) => toast("success", "Grades released!", `${s.released} students notified`),
        onError: (e: Error) => toast("error", "Release failed", e.message),
    });

    return (
        <div className="flex flex-col gap-6">
            {/* Auth status */}
            <div className={`card ${authStatus?.authenticated ? "" : ""}`} style={{
                borderColor: authStatus?.authenticated ? "rgba(34,197,94,0.3)" : "var(--border)",
            }}>
                <div className="flex items-center gap-3">
                    {authStatus?.authenticated
                        ? <CheckCircle size={18} style={{ color: "var(--success)" }} />
                        : <XCircle size={18} style={{ color: "var(--danger)" }} />}
                    <div>
                        <div className="font-semibold" style={{ fontSize: 14 }}>
                            {authStatus?.authenticated ? "Google Classroom Connected" : "Classroom Not Connected"}
                        </div>
                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                            {authStatus?.friendly_scopes?.join(" · ") || authStatus?.scopes?.length + " scopes" || "Checking…"}
                        </div>
                    </div>
                </div>
            </div>

            {/* Coursework link */}
            {!assignment.classroom_id && (
                <div className="card" style={{ borderColor: "rgba(245,158,11,0.3)" }}>
                    <div className="flex items-center gap-3">
                        <AlertTriangle size={16} style={{ color: "var(--warning)" }} />
                        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                            No Classroom coursework linked. Edit the assignment to add a Coursework ID.
                        </div>
                    </div>
                </div>
            )}

            {/* Sync stats */}
            <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                {[
                    { label: "Total Submissions", value: status?.total_submissions ?? "—" },
                    { label: "Graded", value: status?.graded ?? "—" },
                    { label: "Ungraded", value: status?.ungraded ?? "—" },
                ].map(({ label, value }) => (
                    <div key={label} className="stat-card">
                        <div className="stat-label">{label}</div>
                        <div className="stat-value" style={{ fontSize: 24 }}>{String(value)}</div>
                    </div>
                ))}
            </div>

            {/* Actions */}
            <div className="card">
                <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>Sync Actions</h3>
                <div className="flex flex-col gap-3">
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-3)" }}>
                        <button
                            className="btn btn-secondary"
                            onClick={() => ingest.mutate()}
                            disabled={ingest.isPending || !authStatus?.authenticated}
                        >
                            <Download size={13} />
                            {ingest.isPending ? "Pulling…" : "Pull Submissions"}
                        </button>
                        <button
                            className="btn btn-secondary"
                            onClick={() => syncDraft.mutate()}
                            disabled={syncDraft.isPending || !authStatus?.authenticated}
                        >
                            <Send size={13} />
                            {syncDraft.isPending ? "Pushing…" : "Push Draft Grades"}
                        </button>
                        <button
                            className="btn btn-success"
                            onClick={() => release.mutate()}
                            disabled={release.isPending || !authStatus?.authenticated}
                        >
                            <Globe size={13} />
                            {release.isPending ? "Releasing…" : "Release Grades"}
                        </button>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        ⚠ Releasing grades marks them as returned in Google Classroom and makes them visible to students.
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────

const TABS = [
    { id: "overview", label: "Overview", icon: BookOpen },
    { id: "submissions", label: "Submissions", icon: FileText },
    { id: "rubric", label: "Rubric", icon: Edit3 },
    { id: "classroom", label: "Classroom", icon: Globe },
];

export default function AssignmentDetailPage() {
    const { id } = useParams<{ id: string }>();
    const router = useRouter();
    const qc = useQueryClient();
    const { actor } = useAuth();
    const { toast } = useToast();
    const [activeTab, setActiveTab] = useState("overview");
    const [publishConfirm, setPublishConfirm] = useState(false);

    const { data: assignment, isLoading: aLoading } = useQuery({
        queryKey: ["assignment", id],
        queryFn: () => api.assignments.get(id),
    });
    const { data: rubric, refetch: refetchRubric } = useQuery({
        queryKey: ["rubric", id],
        queryFn: () => api.rubrics.getForAssignment(id),
        enabled: !!id,
    });
    const { data: validation, refetch: refetchValidation } = useQuery({
        queryKey: ["validation", id],
        queryFn: () => api.assignments.validatePublish(id),
        enabled: !!id,
    });

    const publishMutation = useMutation({
        mutationFn: () => api.assignments.publish(id, actor ?? "ta", undefined, assignment?.is_published),
        onSuccess: () => {
            toast("success", "Assignment published!", "Submissions can now be graded.");
            qc.invalidateQueries({ queryKey: ["assignment", id] });
            refetchValidation();
            setPublishConfirm(false);
        },
        onError: (e: Error) => { toast("error", "Publish failed", e.message); setPublishConfirm(false); },
    });

    if (aLoading) {
        return (
            <PageShell>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                    {[...Array(4)].map((_, i) => (
                        <div key={i} className="skeleton" style={{ height: i === 0 ? 60 : 120, borderRadius: "var(--radius-lg)" }} />
                    ))}
                </div>
            </PageShell>
        );
    }

    if (!assignment) {
        return (
            <PageShell>
                <div className="empty-state">
                    <AlertTriangle size={40} className="empty-icon" />
                    <div className="empty-title">Assignment not found</div>
                    <button className="btn btn-secondary" onClick={() => router.back()}>Go back</button>
                </div>
            </PageShell>
        );
    }

    return (
        <PageShell>
            <div className="animate-fade-up">
                {/* Header */}
                <div style={{ marginBottom: "var(--space-6)" }}>
                    <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-3)" }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => router.push("/assignments")}>
                            <ArrowLeft size={13} /> Assignments
                        </button>
                        <ChevronRight size={13} style={{ color: "var(--text-muted)" }} />
                        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{assignment.course_id}</span>
                    </div>
                    <div className="flex items-start justify-between">
                        <div>
                            <div className="flex items-center gap-3">
                                <h1 className="page-title">{assignment.title}</h1>
                                <StatusBadge published={assignment.is_published} />
                                {assignment.has_code_question && <span className="badge badge-accent"><Code2 size={10} /> Coding</span>}
                            </div>
                            <p className="page-subtitle">
                                {assignment.max_marks} marks · {assignment.question_type}
                                {assignment.deadline && ` · Due ${new Date(assignment.deadline).toLocaleDateString()}`}
                            </p>
                        </div>
                        <div className="page-actions">
                            <button
                                className="btn btn-primary"
                                onClick={() => setPublishConfirm(true)}
                            >
                                {assignment.is_published ? <><RefreshCw size={13} />Republish</> : <><Send size={13} /> Publish</>}
                            </button>
                        </div>
                    </div>
                </div>

                {/* Tabs */}
                <div className="tabs" style={{ marginBottom: "var(--space-6)" }}>
                    {TABS.map(({ id: tid, label, icon: Icon }) => (
                        <button
                            key={tid}
                            className={`tab ${activeTab === tid ? "active" : ""}`}
                            onClick={() => setActiveTab(tid)}
                        >
                            <Icon size={13} /> {label}
                        </button>
                    ))}
                </div>

                {/* Tab content */}
                {activeTab === "overview" && (
                    <OverviewTab
                        assignment={assignment}
                        rubric={rubric ?? null}
                        validation={validation ?? null}
                        onPublish={() => setPublishConfirm(true)}
                        publishing={publishMutation.isPending}
                        onSwitchTab={setActiveTab}
                    />
                )}
                {activeTab === "submissions" && (
                    <SubmissionsTab assignmentId={id} />
                )}
                {activeTab === "rubric" && (
                    <RubricTab
                        assignment={assignment}
                        rubric={rubric ?? null}
                        onRefresh={() => refetchRubric()}
                    />
                )}
                {activeTab === "classroom" && (
                    <ClassroomTab assignment={assignment} />
                )}
            </div>

            {/* Publish confirm */}
            <ConfirmModal
                open={publishConfirm}
                variant={assignment.is_published ? "warning" : "default"}
                title={assignment.is_published ? "Republish Assignment" : "Publish Assignment"}
                message={
                    assignment.is_published
                        ? "This will update the published state. Existing submissions won't be affected."
                        : <>Ready to publish <strong style={{ color: "var(--text-primary)" }}>{assignment.title}</strong>? After publishing, grading can begin.</>
                }
                confirmText={assignment.is_published ? "Republish" : "Publish"}
                onConfirm={() => publishMutation.mutate()}
                onCancel={() => setPublishConfirm(false)}
                loading={publishMutation.isPending}
            />

            <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
        </PageShell>
    );
}
