"use client";
import React, { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeft, ChevronRight, Edit3, RefreshCw,
    CheckCircle, XCircle, Clock, Send, AlertTriangle, X, Save,
    PenLine, SlidersHorizontal,
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { OcrBlock } from "@/lib/types";

const STATUS_CLASS: Record<string, string> = {
    pending: "badge-default", processing: "badge-warning",
    ocr_done: "badge-info", grading: "badge-accent",
    graded: "badge-success", failed: "badge-danger",
};
const STATUS_LABEL: Record<string, string> = {
    pending: "Pending OCR", processing: "Processing", ocr_done: "OCR Done",
    grading: "Grading", graded: "Graded", failed: "Failed",
};

export default function SubmissionDetailPage() {
    const { id } = useParams<{ id: string }>();
    const router = useRouter();
    const qc = useQueryClient();
    const { actor } = useAuth();
    const { toast } = useToast();

    const [editingBlock, setEditingBlock] = useState<number | null>(null);
    const [editContent, setEditContent] = useState("");
    const [editReason, setEditReason] = useState("");
    const [regradeConfirm, setRegradeConfirm] = useState(false);
    const [releaseConfirm, setReleaseConfirm] = useState(false);
    const [showOverride, setShowOverride] = useState(false);
    const [overrideScore, setOverrideScore] = useState("");
    const [overrideBreakdown, setOverrideBreakdown] = useState("{}");
    const [overrideReason, setOverrideReason] = useState("");
    const [overrideJsonError, setOverrideJsonError] = useState<string | null>(null);

    const { data: sub, isLoading: sLoading } = useQuery({
        queryKey: ["submission", id],
        queryFn: () => api.submissions.detail(id),
        refetchInterval: (q) => {
            const data = q.state.data;
            return data && ["pending", "processing", "grading"].includes(data.status) ? 2500 : false;
        },
    });
    const { data: grade } = useQuery({
        queryKey: ["grade", id],
        queryFn: () => api.submissions.grade(id),
        enabled: sub?.status === "graded",
    });
    const { data: audit = [] } = useQuery({
        queryKey: ["audit", id],
        queryFn: () => api.submissions.audit(id),
    });

    const ocrEditMutation = useMutation({
        mutationFn: ({ block_index, new_content, reason }: { block_index: number; new_content: string; reason: string }) =>
            api.submissions.correctOcr(id, { block_index, new_content, reason, changed_by: actor ?? "ta" }),
        onSuccess: () => {
            toast("success", "OCR corrected", "Re-grading has been triggered automatically.");
            qc.invalidateQueries({ queryKey: ["submission", id] });
            setEditingBlock(null);
        },
        onError: (e: Error) => toast("error", "Correction failed", e.message),
    });

    const regradeMutation = useMutation({
        mutationFn: () => api.submissions.regrade(id, "Instructor requested regrade", actor ?? "ta"),
        onSuccess: () => {
            toast("success", "Regrade requested");
            qc.invalidateQueries({ queryKey: ["submission", id] });
            setRegradeConfirm(false);
        },
        onError: (e: Error) => toast("error", "Regrade failed", e.message),
    });

    const releaseMutation = useMutation({
        mutationFn: () => api.grades.release([id]),
        onSuccess: () => {
            toast("success", "Grade released to student");
            qc.invalidateQueries({ queryKey: ["submission", id] });
            qc.invalidateQueries({ queryKey: ["grade", id] });
            setReleaseConfirm(false);
        },
        onError: (e: Error) => toast("error", "Release failed", e.message),
    });

    const overrideMutation = useMutation({
        mutationFn: () => {
            let breakdown: Record<string, unknown>;
            try { breakdown = JSON.parse(overrideBreakdown); } catch { throw new Error("breakdown_json is not valid JSON"); }
            return api.submissions.overrideGrade(id, {
                total_score: parseFloat(overrideScore),
                breakdown_json: breakdown,
                reason: overrideReason,
                changed_by: actor ?? "ta",
            });
        },
        onSuccess: () => {
            toast("success", "Grade overridden", "Manual grade saved successfully.");
            qc.invalidateQueries({ queryKey: ["grade", id] });
            qc.invalidateQueries({ queryKey: ["audit", id] });
            qc.invalidateQueries({ queryKey: ["submission", id] });
            setShowOverride(false);
        },
        onError: (e: Error) => toast("error", "Override failed", e.message),
    });

    const openOverride = () => {
        // Pre-fill from current grade if available
        if (grade) {
            setOverrideScore(String(grade.total_score));
            setOverrideBreakdown(JSON.stringify(grade.breakdown_json, null, 2));
        } else {
            setOverrideScore("");
            setOverrideBreakdown("{}");
        }
        setOverrideReason("");
        setOverrideJsonError(null);
        setShowOverride(true);
    };

    const validateBreakdown = (v: string) => {
        try { JSON.parse(v); setOverrideJsonError(null); } catch { setOverrideJsonError("Invalid JSON"); }
        setOverrideBreakdown(v);
    };

    const startEdit = (block: OcrBlock) => {
        setEditingBlock(block.index);
        setEditContent(block.content);
        setEditReason("");
    };

    const saveEdit = () => {
        if (editingBlock === null) return;
        ocrEditMutation.mutate({ block_index: editingBlock, new_content: editContent.trim(), reason: editReason });
    };

    if (sLoading) {
        return (
            <PageShell>
                <div className="flex flex-col gap-4">
                    {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 200, borderRadius: "var(--radius-lg)" }} />)}
                </div>
            </PageShell>
        );
    }

    if (!sub) {
        return (
            <PageShell>
                <div className="empty-state">
                    <AlertTriangle size={40} className="empty-icon" />
                    <div className="empty-title">Submission not found</div>
                    <button className="btn btn-secondary" onClick={() => router.back()}>Go back</button>
                </div>
            </PageShell>
        );
    }

    const blocks: OcrBlock[] = sub.ocr_result?.blocks ?? [];
    const maxMarks = sub.assignment_max_marks || 100;
    const pct = grade ? Math.round((grade.total_score / maxMarks) * 100) : null;

    return (
        <PageShell>
            <div className="animate-fade-up">
                {/* Breadcrumb */}
                <div className="flex items-center gap-2" style={{ marginBottom: "var(--space-4)", fontSize: 13, color: "var(--text-muted)" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => router.back()}>
                        <ArrowLeft size={13} /> Submissions
                    </button>
                    <ChevronRight size={13} />
                    <span>{sub.assignment_title || "Assignment"}</span>
                    <ChevronRight size={13} />
                    <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{sub.student_id}</span>
                </div>

                {/* Header */}
                <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-6)" }}>
                    <div className="flex items-center gap-3">
                        <h1 className="page-title">{sub.student_name || sub.student_id}</h1>
                        <span className={`badge ${STATUS_CLASS[sub.status]}`} style={{ fontSize: 12 }}>
                            {STATUS_LABEL[sub.status]}
                        </span>
                        {grade && (
                            <div style={{
                                background: "var(--bg-elevated)", border: "1px solid var(--border-medium)",
                                borderRadius: "var(--radius)", padding: "4px 12px",
                                fontSize: 13, fontWeight: 600, color: "var(--text-primary)",
                            }}>
                                {grade.total_score}/{maxMarks}
                                <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 4 }}>({pct}%)</span>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => setRegradeConfirm(true)}
                            disabled={sub.status === "grading" || sub.status === "processing"}
                        >
                            <RefreshCw size={13} /> Regrade
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={openOverride}>
                            <SlidersHorizontal size={13} /> Manual Override
                        </button>
                        {sub.status === "graded" && (
                            <button className="btn btn-primary btn-sm" onClick={() => setReleaseConfirm(true)}>
                                <Send size={13} /> Release Grade
                            </button>
                        )}
                    </div>
                </div>

                {/* 3-panel layout */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-4)" }}>

                    {/* Panel 1: Submission image */}
                    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                        <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", fontSize: 13, fontWeight: 600 }}>
                            Scan Image
                        </div>
                        <div style={{ background: "var(--bg-base)", minHeight: 400, display: "flex", alignItems: "center", justifyContent: "center" }}>
                            {sub.status === "pending" ? (
                                <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "var(--space-6)" }}>
                                    <Clock size={28} style={{ margin: "0 auto var(--space-3)", opacity: 0.3 }} />
                                    <div style={{ fontSize: 13 }}>Processing…</div>
                                </div>
                            ) : (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                    src={api.submissions.imageUrl(id)}
                                    alt={`Submission scan for ${sub.student_id}`}
                                    style={{ width: "100%", height: "auto", maxHeight: 600, objectFit: "contain" }}
                                    onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                                />
                            )}
                        </div>
                    </div>

                    {/* Panel 2: OCR Blocks */}
                    <div className="card" style={{ padding: 0 }}>
                        <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            <span style={{ fontSize: 13, fontWeight: 600 }}>OCR Text</span>
                            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{blocks.length} blocks</span>
                        </div>
                        <div style={{ padding: "var(--space-3)", overflow: "auto", maxHeight: 600 }}>
                            {blocks.length === 0 ? (
                                <div className="empty-state" style={{ padding: "var(--space-8)" }}>
                                    <div className="empty-title">No OCR data</div>
                                    <div className="empty-message">OCR hasn't run yet or produced no blocks.</div>
                                </div>
                            ) : blocks.map((block, idx) => (
                                <div key={idx} style={{
                                    marginBottom: "var(--space-2)",
                                    borderRadius: "var(--radius)",
                                    border: `1px solid ${editingBlock === block.index ? "var(--accent)" : block.flagged ? "rgba(245,158,11,0.4)" : "var(--border)"}`,
                                    background: editingBlock === block.index ? "var(--accent-dim)" : "var(--bg-elevated)",
                                    overflow: "hidden",
                                }}>
                                    <div style={{
                                        display: "flex", alignItems: "center", justifyContent: "space-between",
                                        padding: "6px var(--space-3)",
                                        borderBottom: editingBlock === block.index ? "1px solid var(--border)" : "none",
                                    }}>
                                        <div className="flex items-center gap-2">
                                            <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", width: 20 }}>
                                                #{block.index + 1}
                                            </span>
                                            {block.flagged && <span className="badge badge-warning" style={{ fontSize: 10 }}>Flagged</span>}
                                            {block.confidence !== undefined && (
                                                <span style={{ fontSize: 10, color: block.confidence > 0.7 ? "var(--success)" : "var(--warning)" }}>
                                                    {Math.round(block.confidence * 100)}%
                                                </span>
                                            )}
                                        </div>
                                        {editingBlock !== block.index ? (
                                            <button className="btn btn-ghost btn-icon btn-sm" onClick={() => startEdit(block)}>
                                                <Edit3 size={12} />
                                            </button>
                                        ) : (
                                            <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setEditingBlock(null)}>
                                                <X size={12} />
                                            </button>
                                        )}
                                    </div>

                                    {editingBlock === block.index ? (
                                        <div style={{ padding: "var(--space-3)" }}>
                                            <textarea
                                                className="input"
                                                rows={3}
                                                value={editContent}
                                                onChange={e => setEditContent(e.target.value)}
                                                style={{ marginBottom: "var(--space-2)", fontSize: 12 }}
                                            />
                                            <input
                                                className="input"
                                                placeholder="Reason for correction…"
                                                value={editReason}
                                                onChange={e => setEditReason(e.target.value)}
                                                style={{ marginBottom: "var(--space-2)", fontSize: 12 }}
                                            />
                                            <button
                                                className="btn btn-primary btn-sm w-full"
                                                onClick={saveEdit}
                                                disabled={ocrEditMutation.isPending}
                                            >
                                                <Save size={12} /> {ocrEditMutation.isPending ? "Saving…" : "Save & Regrade"}
                                            </button>
                                        </div>
                                    ) : (
                                        <div style={{ padding: "8px var(--space-3)", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6, fontFamily: "var(--font-mono)" }}>
                                            {block.content}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Panel 3: Grade + Audit */}
                    <div className="flex flex-col gap-4">
                        {/* Grade */}
                        <div className="card" style={{ padding: 0 }}>
                            <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", fontSize: 13, fontWeight: 600 }}>
                                Grade
                            </div>
                            <div style={{ padding: "var(--space-4)" }}>
                                {!grade ? (
                                    <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "var(--space-6)", fontSize: 13 }}>
                                        {sub.status === "grading" ? "Grading in progress…" : "No grade yet"}
                                    </div>
                                ) : (
                                    <>
                                        {/* Score */}
                                        <div style={{
                                            display: "flex", alignItems: "baseline", gap: "var(--space-2)",
                                            marginBottom: "var(--space-3)",
                                        }}>
                                            <span style={{ fontSize: 36, fontWeight: 700, color: "var(--text-primary)" }}>
                                                {grade.total_score}
                                            </span>
                                            <span style={{ fontSize: 16, color: "var(--text-muted)" }}>/ {maxMarks}</span>
                                            <span style={{ fontSize: 13, color: "var(--text-muted)", marginLeft: "auto" }}>{pct}%</span>
                                        </div>

                                        {/* Progress */}
                                        <div className="progress-wrap" style={{ marginBottom: "var(--space-4)" }}>
                                            <div
                                                className={`progress-bar ${pct! >= 70 ? "success" : pct! >= 40 ? "warning" : "danger"}`}
                                                style={{ width: `${pct}%` }}
                                            />
                                        </div>

                                        {/* Source + Classroom */}
                                        <div className="flex items-center gap-2" style={{ marginBottom: "var(--space-4)" }}>
                                            <span className="badge badge-default">{grade.source.replace(/_/g, " ")}</span>
                                            <span className={`badge ${grade.classroom_status === "released" ? "badge-success" : grade.classroom_status === "draft" ? "badge-info" : "badge-default"}`}>
                                                {grade.classroom_status.replace(/_/g, " ")}
                                            </span>
                                            {grade.is_truncated && <span className="badge badge-warning">Flagged</span>}
                                        </div>

                                        {/* Breakdown */}
                                        <div className="flex flex-col gap-2">
                                            {Object.entries(grade.breakdown_json ?? {}).map(([key, val]) => {
                                                const v = val as { marks: number; feedback: string; max_marks?: number };
                                                return (
                                                    <div key={key} style={{
                                                        padding: "var(--space-3)",
                                                        borderRadius: "var(--radius-sm)",
                                                        background: "var(--bg-elevated)",
                                                        border: "1px solid var(--border)",
                                                    }}>
                                                        <div className="flex items-center justify-between" style={{ marginBottom: 4 }}>
                                                            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>
                                                                {key.replace(/_/g, " ")}
                                                            </span>
                                                            <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>
                                                                {v.marks}{v.max_marks ? `/${v.max_marks}` : ""}
                                                            </span>
                                                        </div>
                                                        {v.feedback && (
                                                            <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                                                {v.feedback}
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Audit log */}
                        <div className="card" style={{ padding: 0, flex: 1 }}>
                            <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", fontSize: 13, fontWeight: 600 }}>
                                Audit Log
                                <span style={{ float: "right", fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                                    {audit.length} entries
                                </span>
                            </div>
                            <div style={{ padding: "var(--space-3)", overflow: "auto", maxHeight: 300 }}>
                                {audit.length === 0 ? (
                                    <div style={{ textAlign: "center", padding: "var(--space-6)", fontSize: 12, color: "var(--text-muted)" }}>
                                        No audit entries yet
                                    </div>
                                ) : [...audit].reverse().map((entry, i) => (
                                    <div key={i} style={{
                                        padding: "var(--space-2) var(--space-3)",
                                        borderBottom: "1px solid var(--border)",
                                        fontSize: 12,
                                    }}>
                                        <div className="flex items-center justify-between" style={{ marginBottom: 2 }}>
                                            <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                                                {entry.action.replace(/_/g, " ")}
                                            </span>
                                            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                                                {new Date(entry.timestamp).toLocaleString()}
                                            </span>
                                        </div>
                                        <div style={{ color: "var(--text-muted)" }}>
                                            by {entry.changed_by}
                                            {entry.reason ? ` · ${entry.reason}` : ""}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Modals */}
            <ConfirmModal
                open={regradeConfirm}
                title="Request AI Regrade"
                message="This will re-run AI grading on the existing OCR text with the current rubric. The current grade will be replaced."
                confirmText="Regrade"
                onConfirm={() => regradeMutation.mutate()}
                onCancel={() => setRegradeConfirm(false)}
                loading={regradeMutation.isPending}
            />
            <ConfirmModal
                open={releaseConfirm}
                variant="warning"
                title="Release Grade to Student"
                message="This will make the grade visible to the student in Google Classroom."
                confirmText="Release"
                onConfirm={() => releaseMutation.mutate()}
                onCancel={() => setReleaseConfirm(false)}
                loading={releaseMutation.isPending}
            />

            {/* Manual Override Panel */}
            {showOverride && (
                <div style={{ position: "fixed", inset: 0, zIndex: 200, display: "flex", justifyContent: "flex-end" }}>
                    <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.5)" }} onClick={() => setShowOverride(false)} />
                    <div style={{
                        position: "relative", width: 440, background: "var(--bg-card)",
                        borderLeft: "1px solid var(--border-medium)", padding: "var(--space-6)",
                        overflowY: "auto", display: "flex", flexDirection: "column", gap: "var(--space-4)",
                    }}>
                        <div className="flex items-center justify-between">
                            <h2 style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
                                <PenLine size={14} style={{ marginRight: 8, display: "inline" }} />
                                Manual Grade Override
                            </h2>
                            <button className="btn btn-ghost btn-sm" onClick={() => setShowOverride(false)}><X size={14} /></button>
                        </div>

                        <div style={{
                            padding: "var(--space-3)", borderRadius: "var(--radius)",
                            background: "var(--warning-dim)", border: "1px solid rgba(245,158,11,0.3)",
                            fontSize: 12, color: "var(--text-secondary)",
                        }}>
                            ⚠ A manual override will deactivate the current AI-generated grade and create a new <code>TA_Manual</code> grade. This action is audited.
                        </div>

                        <div className="input-group">
                            <label className="input-label">Total Score (out of {maxMarks})</label>
                            <input
                                type="number" className="input"
                                min={0} max={maxMarks} step={0.5}
                                value={overrideScore}
                                onChange={e => setOverrideScore(e.target.value)}
                                placeholder={`0 – ${maxMarks}`}
                            />
                        </div>

                        <div className="input-group">
                            <label className="input-label">Breakdown JSON</label>
                            <textarea
                                className={`input ${overrideJsonError ? "input-error" : ""}`}
                                rows={8}
                                value={overrideBreakdown}
                                onChange={e => validateBreakdown(e.target.value)}
                                style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
                                placeholder={'{ "q1": { "marks": 8, "max_marks": 10, "feedback": "Good work" } }'}
                            />
                            {overrideJsonError && (
                                <span className="input-hint" style={{ color: "var(--danger)" }}>{overrideJsonError}</span>
                            )}
                            <span className="input-hint">Keep keys matching your rubric question IDs.</span>
                        </div>

                        <div className="input-group">
                            <label className="input-label">Reason / Notes *</label>
                            <textarea
                                className="input" rows={3}
                                value={overrideReason}
                                onChange={e => setOverrideReason(e.target.value)}
                                placeholder="e.g. AI missed marks for partial credit in Q3"
                            />
                        </div>

                        <div className="flex gap-3" style={{ marginTop: "auto" }}>
                            <button className="btn btn-secondary flex-1" onClick={() => setShowOverride(false)}>Cancel</button>
                            <button
                                className="btn btn-primary flex-1"
                                onClick={() => overrideMutation.mutate()}
                                disabled={
                                    overrideMutation.isPending ||
                                    !!overrideJsonError ||
                                    !overrideScore ||
                                    !overrideReason.trim()
                                }
                            >
                                {overrideMutation.isPending ? "Saving…" : <><Save size={13} /> Save Override</>}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </PageShell>
    );
}
