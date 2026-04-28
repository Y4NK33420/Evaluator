"use client";
import React, { useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeft, ChevronRight, Edit3, RefreshCw, Play,
    CheckCircle, XCircle, Clock, Send, AlertTriangle, X, Save,
    PenLine, SlidersHorizontal, Code2, FileCode, Terminal,
    ExternalLink, Sparkles,
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
    pending: "Pending", processing: "Processing",
    ocr_done: "Ready to Evaluate", grading: "Evaluating",
    graded: "Graded", failed: "Failed",
};
const JOB_STATUS_CLASS: Record<string, string> = {
    QUEUED: "badge-default", EXECUTING_RAW: "badge-warning",
    AI_ANALYZING: "badge-accent", RETRYING_SHIM: "badge-warning",
    FINALIZING: "badge-accent", COMPLETED: "badge-success", FAILED: "badge-danger",
};

// ── Grade panel (shared) ──────────────────────────────────────────────────────

function GradePanel({ grade, maxMarks }: { grade: { total_score: number; breakdown_json: Record<string, unknown>; source: string; classroom_status: string; is_truncated: boolean } | undefined; maxMarks: number }) {
    const pct = grade ? Math.round((grade.total_score / maxMarks) * 100) : null;
    return (
        <div className="card" style={{ padding: 0 }}>
            <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Grade</span>
                {grade && <span className={`badge ${grade.classroom_status === "released" ? "badge-success" : grade.classroom_status === "draft" ? "badge-info" : "badge-default"}`} style={{ fontSize: 10 }}>{grade.classroom_status.replace(/_/g, " ")}</span>}
            </div>
            <div style={{ padding: "var(--space-4)" }}>
                {!grade ? (
                    <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "var(--space-6)", fontSize: 13 }}>
                        <Clock size={24} style={{ margin: "0 auto var(--space-2)", opacity: 0.3 }} />
                        No grade yet
                    </div>
                ) : (
                    <>
                        <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)", marginBottom: "var(--space-3)" }}>
                            <span style={{ fontSize: 40, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1 }}>{grade.total_score}</span>
                            <span style={{ fontSize: 18, color: "var(--text-muted)" }}>/ {maxMarks}</span>
                            <span style={{ fontSize: 13, fontWeight: 600, color: pct! >= 70 ? "var(--success)" : pct! >= 40 ? "var(--warning)" : "var(--danger)", marginLeft: "auto" }}>{pct}%</span>
                        </div>
                        <div className="progress-wrap" style={{ marginBottom: "var(--space-4)" }}>
                            <div className={`progress-bar ${pct! >= 70 ? "success" : pct! >= 40 ? "warning" : "danger"}`} style={{ width: `${pct}%` }} />
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
                            <span className="badge badge-default" title="Grading source">{grade.source.replace(/_/g, " ")}</span>
                            {grade.is_truncated && <span className="badge badge-warning">⚠ Truncated</span>}
                        </div>
                        <GradeBreakdown fullResult={grade.breakdown_json} />
                    </>
                )}
            </div>
        </div>
    );
}

function GradeBreakdown({ fullResult }: { fullResult: Record<string, unknown> }) {
    const breakdown = fullResult?.breakdown as Record<string, { marks_awarded?: number; max_marks?: number; feedback?: string; is_truncated?: boolean }> | undefined;
    const scoreBreakdown = fullResult?.score_breakdown as {
        correctness_score?: number;
        max_score?: number;
        correctness_percent?: number;
        quality_applied?: boolean;
        quality_mode?: string;
        quality_weight_percent?: number;
        quality_score?: number | null;
        total_score?: number;
        total_percent?: number;
    } | undefined;
    // testcase_results key for code-eval grades
    const testcaseResults = fullResult?.testcase_results as Array<{ testcase_id: string; passed: boolean; score: number; stdout?: string; stderr?: string }> | undefined;
    const stepScores = (fullResult?.score_details as Record<string, unknown> | undefined)?.rubric_step_scores as Array<{ question_id: string; step_id: string; step: string; marks_awarded: number; max_marks: number; feedback: string }> | undefined;
    const model = fullResult?.model as string | undefined;
    const scoringMode = fullResult?.scoring_mode as string | undefined;
    const qualityEval = fullResult?.quality_evaluation as {
        quality_score?: number;
        weight_percent?: number;
    } | undefined;

    if (testcaseResults && testcaseResults.length > 0) {
        // Code-eval grade breakdown
        const passed = testcaseResults.filter(t => t.passed).length;
        return (
            <div className="flex flex-col gap-2">
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>
                    Test Results — {passed}/{testcaseResults.length} passed
                </div>
                {testcaseResults.map((tc, i) => (
                    <details key={i} style={{ borderRadius: "var(--radius-sm)", border: `1px solid ${tc.passed ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`, overflow: "hidden" }}>
                        <summary style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", padding: "var(--space-2) var(--space-3)", background: tc.passed ? "rgba(34,197,94,0.05)" : "rgba(239,68,68,0.05)", cursor: "pointer", listStyle: "none" }}>
                            {tc.passed ? <CheckCircle size={13} style={{ color: "var(--success)", flexShrink: 0 }} /> : <XCircle size={13} style={{ color: "var(--danger)", flexShrink: 0 }} />}
                            <span style={{ flex: 1, fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{tc.testcase_id}</span>
                            <span style={{ fontSize: 12, fontWeight: 600, color: tc.passed ? "var(--success)" : "var(--danger)" }}>{tc.score.toFixed(1)}</span>
                        </summary>
                        {(tc.stdout || tc.stderr) && (
                            <div style={{ background: "var(--bg-base)", padding: "var(--space-2) var(--space-3)", borderTop: "1px solid var(--border)" }}>
                                {tc.stdout && <pre style={{ fontSize: 10, color: "var(--text-secondary)", margin: 0, whiteSpace: "pre-wrap", maxHeight: 80, overflow: "auto" }}>{tc.stdout}</pre>}
                                {tc.stderr && <pre style={{ fontSize: 10, color: "var(--danger)", margin: 0, whiteSpace: "pre-wrap", maxHeight: 60, overflow: "auto" }}>{tc.stderr}</pre>}
                            </div>
                        )}
                    </details>
                ))}
                {model && <span className="badge badge-default" style={{ fontSize: 10, alignSelf: "flex-start" }}>{model}</span>}
            </div>
        );
    }

    if (!breakdown || Object.keys(breakdown).length === 0) {
        if (scoreBreakdown) {
            const maxScore = scoreBreakdown.max_score ?? 0;
            const totalScore = scoreBreakdown.total_score ?? 0;
            const qualityWeight = (scoreBreakdown.quality_weight_percent ?? qualityEval?.weight_percent ?? 0) / 100;
            const rawQualityScore = scoreBreakdown.quality_score ?? qualityEval?.quality_score;
            const qualityTotal = maxScore * qualityWeight;
            const testcaseTotal = maxScore - qualityTotal;
            const qualityMarks = (rawQualityScore !== undefined && rawQualityScore !== null)
                ? maxScore * qualityWeight * (Number(rawQualityScore) / 100)
                : null;
            const correctnessMarks = qualityMarks !== null
                ? totalScore - qualityMarks
                : (scoreBreakdown.correctness_score ?? 0);
            return (
                <div className="flex flex-col gap-2">
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>
                        Score Breakdown
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-2)" }}>
                        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)" }}>
                            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Testcases</div>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>
                                {correctnessMarks.toFixed(2)}
                                {` / ${testcaseTotal.toFixed(2)}`}
                            </div>
                            {scoreBreakdown.correctness_percent !== undefined && testcaseTotal > 0 && (
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                    {Math.round((correctnessMarks / testcaseTotal) * 100)}%
                                </div>
                            )}
                        </div>
                        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)" }}>
                            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Total</div>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>
                                {scoreBreakdown.total_score ?? 0}
                                {scoreBreakdown.max_score !== undefined ? ` / ${scoreBreakdown.max_score}` : ""}
                            </div>
                            {scoreBreakdown.total_percent !== undefined && (
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{scoreBreakdown.total_percent}%</div>
                            )}
                        </div>
                    </div>
                    {qualityMarks !== null && (
                        <div style={{ marginTop: "var(--space-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)" }}>
                            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Quality</div>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>
                                {qualityMarks.toFixed(2)} / {qualityTotal.toFixed(2)}
                            </div>
                            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                raw quality {rawQualityScore ?? 0}/100 · weight {scoreBreakdown.quality_weight_percent ?? qualityEval?.weight_percent ?? 0}%
                            </div>
                        </div>
                    )}
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-1)" }}>
                        <span className="badge badge-default" style={{ fontSize: 10 }}>
                            Quality {scoreBreakdown.quality_applied ? "applied" : "not applied"}
                        </span>
                        {scoreBreakdown.quality_mode && (
                            <span className="badge badge-default" style={{ fontSize: 10 }}>
                                {scoreBreakdown.quality_mode.replace(/_/g, " ")}
                            </span>
                        )}
                        {scoreBreakdown.quality_weight_percent !== undefined && (
                            <span className="badge badge-default" style={{ fontSize: 10 }}>
                                weight {scoreBreakdown.quality_weight_percent}%
                            </span>
                        )}
                    </div>
                </div>
            );
        }
        return <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", padding: "var(--space-4)" }}>No breakdown available.</div>;
    }

    return (
        <div className="flex flex-col gap-2">
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>Score Breakdown</div>
            {Object.entries(breakdown).map(([qid, qdata]) => {
                const scored = qdata.marks_awarded ?? 0;
                const maxQ = qdata.max_marks;
                const qPct = maxQ ? Math.round((scored / maxQ) * 100) : null;
                const steps = stepScores?.filter(s => s.question_id === qid) ?? [];
                return (
                    <details key={qid} style={{ borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", overflow: "hidden" }}>
                        <summary style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)", cursor: "pointer", listStyle: "none" }}>
                            <div style={{ width: 26, height: 26, borderRadius: "var(--radius-sm)", background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "var(--accent)", flexShrink: 0 }}>
                                {qid.replace(/[^0-9]/g, "") || qid}
                            </div>
                            <span style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{qid}</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: qPct !== null && qPct >= 70 ? "var(--success)" : qPct !== null && qPct < 40 ? "var(--danger)" : "var(--text-primary)" }}>
                                {scored}{maxQ !== undefined ? `/${maxQ}` : ""}
                            </span>
                            {qPct !== null && <span style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 32, textAlign: "right" }}>{qPct}%</span>}
                        </summary>
                        <div style={{ background: "var(--bg-surface)", borderTop: "1px solid var(--border)" }}>
                            {qdata.feedback && <div style={{ padding: "var(--space-2) var(--space-3)", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>{qdata.feedback}</div>}
                            {steps.map((s, si) => (
                                <div key={si} style={{ display: "flex", alignItems: "flex-start", gap: "var(--space-3)", padding: "var(--space-2) var(--space-3)", borderTop: "1px solid var(--border)" }}>
                                    <div style={{ width: 20, fontSize: 10, color: "var(--text-muted)", flexShrink: 0, paddingTop: 2 }}>S{si + 1}</div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.4 }}>{s.step}</div>
                                        {s.feedback && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, fontStyle: "italic" }}>{s.feedback}</div>}
                                    </div>
                                    <span style={{ fontSize: 12, fontWeight: 600, color: s.marks_awarded >= s.max_marks ? "var(--success)" : s.marks_awarded === 0 ? "var(--danger)" : "var(--warning)", flexShrink: 0 }}>
                                        {s.marks_awarded}/{s.max_marks}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </details>
                );
            })}
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-2)" }}>
                {scoringMode && <span className="badge badge-default" style={{ fontSize: 10 }}>{scoringMode.replace(/_/g, " ")}</span>}
                {model && <span className="badge badge-default" style={{ fontSize: 10 }}>{model}</span>}
            </div>
        </div>
    );
}

// ── Audit Panel (shared) ──────────────────────────────────────────────────────

function AuditPanel({ audit }: { audit: { action: string; changed_by: string; reason: string | null; new_value_json: Record<string, unknown> | null; timestamp: string }[] }) {
    return (
        <div className="card" style={{ padding: 0 }}>
            <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", fontSize: 13, fontWeight: 600 }}>
                Audit Log <span style={{ float: "right", fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>{audit.length} entries</span>
            </div>
            <div style={{ padding: "var(--space-3)", overflow: "auto", maxHeight: 280 }}>
                {audit.length === 0 ? (
                    <div style={{ textAlign: "center", padding: "var(--space-6)", fontSize: 12, color: "var(--text-muted)" }}>No audit entries yet</div>
                ) : [...audit].reverse().map((entry, i) => (
                    <div key={i} style={{ padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--border)", fontSize: 12 }}>
                        <div className="flex items-center justify-between" style={{ marginBottom: 2 }}>
                            <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{entry.action.replace(/_/g, " ")}</span>
                            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{new Date(entry.timestamp).toLocaleString()}</span>
                        </div>
                        <div style={{ color: "var(--text-muted)" }}>
                            by {entry.changed_by}{entry.reason ? ` · ${entry.reason}` : ""}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SubmissionDetailPage() {
    const { id } = useParams<{ id: string }>();
    const router = useRouter();
    const searchParams = useSearchParams();
    const qc = useQueryClient();
    const { actor } = useAuth();
    const { toast } = useToast();

    const [editingBlock, setEditingBlock] = useState<number | null>(null);
    const [editContent, setEditContent] = useState("");
    const [editReason, setEditReason] = useState("");
    const [regradeConfirm, setRegradeConfirm] = useState(false);
    const [dispatchConfirm, setDispatchConfirm] = useState(false);
    const [reregradeConfirm, setReregradeConfirm] = useState(false);
    const [releaseConfirm, setReleaseConfirm] = useState(false);
    const [showOverride, setShowOverride] = useState(false);
    const [overrideScore, setOverrideScore] = useState("");
    const [overrideBreakdown, setOverrideBreakdown] = useState("{}");
    const [overrideReason, setOverrideReason] = useState("");
    const [overrideJsonError, setOverrideJsonError] = useState<string | null>(null);
    const [previewPage, setPreviewPage] = useState(1);
    const assignmentIdFromQuery = searchParams.get("assignmentId");

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
        retry: false,
    });
    const { data: audit = [] } = useQuery({
        queryKey: ["audit", id],
        queryFn: () => api.submissions.audit(id),
    });
    const { data: codeEvalJobs = [] } = useQuery({
        queryKey: ["code-eval-jobs", id],
        queryFn: () => api.codeEval.jobs.list({ submission_id: id }),
        enabled: !!sub?.assignment_has_code_question,
        refetchInterval: (q) => {
            const jobs = q.state.data ?? [];
            const hasActive = jobs.some(j => !["COMPLETED", "FAILED"].includes(j.status));
            return hasActive ? 3000 : false;
        },
    });

    /* ── Mutations ────────────────────────────────────────────────────────── */
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

    const dispatchMutation = useMutation({
        mutationFn: (explicit: boolean) => api.submissions.dispatchCodeEval(id, { explicit_regrade: explicit, changed_by: actor ?? "ta" }),
        onSuccess: () => {
            toast("success", "Code-eval job queued!", "Polling for results…");
            qc.invalidateQueries({ queryKey: ["code-eval-jobs", id] });
            qc.invalidateQueries({ queryKey: ["submission", id] });
            setDispatchConfirm(false);
            setReregradeConfirm(false);
        },
        onError: (e: Error) => {
            toast("error", "Dispatch failed", e.message);
            setDispatchConfirm(false);
            setReregradeConfirm(false);
        },
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

    /* ── Helpers ──────────────────────────────────────────────────────────── */
    const openOverride = () => {
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

    /* ── Loading / error states ───────────────────────────────────────────── */
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
                    <button className="btn btn-secondary" onClick={() => router.push(backHref)}>Go back</button>
                </div>
            </PageShell>
        );
    }

    const blocks: OcrBlock[] = sub.ocr_result?.blocks ?? [];
    const maxMarks = sub.assignment_max_marks || 100;
    const isCoding = !!sub.assignment_has_code_question;
    const pageCount = Number(sub.ocr_result?.page_count ?? 1);
    const safePreviewPage = Math.max(1, Math.min(previewPage, pageCount));
    const isMultiPage = pageCount > 1;
    const hasCompletedJob = codeEvalJobs.some(j => j.status === "COMPLETED");
    const hasActiveJob = codeEvalJobs.some(j => !["COMPLETED", "FAILED"].includes(j.status));
    const backHref = sub.assignment_id
        ? `/submissions?assignmentId=${sub.assignment_id}`
        : assignmentIdFromQuery
            ? `/submissions?assignmentId=${assignmentIdFromQuery}`
            : "/submissions";

    /* ── Header action buttons ────────────────────────────────────────────── */
    const headerActions = (
        <div className="flex items-center gap-2">
            {isCoding ? (
                <>
                    {hasCompletedJob ? (
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => setReregradeConfirm(true)}
                            disabled={dispatchMutation.isPending || hasActiveJob}
                            title="Force re-evaluate this submission"
                        >
                            <RefreshCw size={13} /> Re-evaluate
                        </button>
                    ) : (
                        <button
                            className="btn btn-primary btn-sm"
                            onClick={() => setDispatchConfirm(true)}
                            disabled={dispatchMutation.isPending || hasActiveJob || sub.status === "grading"}
                        >
                            {dispatchMutation.isPending || hasActiveJob
                                ? <><RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> Evaluating…</>
                                : <><Play size={13} /> Dispatch Eval</>}
                        </button>
                    )}
                </>
            ) : (
                <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => setRegradeConfirm(true)}
                    disabled={sub.status === "grading" || sub.status === "processing"}
                >
                    <RefreshCw size={13} /> Regrade
                </button>
            )}
            <button className="btn btn-ghost btn-sm" onClick={openOverride}>
                <SlidersHorizontal size={13} /> Manual Override
            </button>
            {sub.status === "graded" && (
                <button className="btn btn-primary btn-sm" onClick={() => setReleaseConfirm(true)}>
                    <Send size={13} /> Release Grade
                </button>
            )}
        </div>
    );

    return (
        <PageShell>
            <div className="animate-fade-up">
                {/* Breadcrumb */}
                <div className="flex items-center gap-2" style={{ marginBottom: "var(--space-4)", fontSize: 13, color: "var(--text-muted)" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => router.push(backHref)}>
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
                        <span className={`badge ${STATUS_CLASS[sub.status]}`} style={{ fontSize: 12 }}>{STATUS_LABEL[sub.status]}</span>
                        {isCoding && <span className="badge badge-accent" style={{ fontSize: 11 }}><Code2 size={10} /> Coding</span>}
                        {grade && (
                            <div style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-medium)", borderRadius: "var(--radius)", padding: "4px 12px", fontSize: 13, fontWeight: 600 }}>
                                {grade.total_score}/{maxMarks}
                                <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 4 }}>({Math.round((grade.total_score / maxMarks) * 100)}%)</span>
                            </div>
                        )}
                    </div>
                    {headerActions}
                </div>

                {/* ── CODING ASSIGNMENT LAYOUT ── */}
                {isCoding ? (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>

                        {/* LEFT: Code file + Eval Jobs */}
                        <div className="flex flex-col gap-4">
                            {/* Code File Card */}
                            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                                <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                    <FileCode size={14} style={{ color: "var(--accent)" }} />
                                    <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>Submitted Code</span>
                                    <span className="badge badge-default" style={{ fontSize: 10 }}>{sub.student_id}</span>
                                </div>
                                <div style={{ background: "var(--bg-base)", minHeight: 180, display: "flex", alignItems: "center", justifyContent: "center", padding: sub.source_code ? 0 : "var(--space-6)", textAlign: sub.source_code ? "left" : "center" }}>
                                    {sub.status === "pending" ? (
                                        <div style={{ color: "var(--text-muted)", width: "100%", padding: "var(--space-6)" }}>
                                            <Clock size={28} style={{ margin: "0 auto var(--space-3)", opacity: 0.3 }} />
                                            <div style={{ fontSize: 13, textAlign: "center" }}>Uploading…</div>
                                        </div>
                                    ) : sub.source_code ? (
                                        <div style={{ width: "100%", height: "100%", maxHeight: 400, overflow: "auto", padding: "var(--space-4)" }}>
                                            <pre style={{ margin: 0, padding: 0, background: "transparent", fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-primary)", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
                                                {sub.source_code}
                                            </pre>
                                        </div>
                                    ) : (
                                        <div style={{ color: "var(--text-muted)", fontSize: 12, width: "100%", padding: "var(--space-6)", textAlign: "center" }}>
                                            <Terminal size={28} style={{ margin: "0 auto var(--space-3)", opacity: 0.4 }} />
                                            <div style={{ marginBottom: "var(--space-1)" }}>Code file stored server-side</div>
                                            <div style={{ fontSize: 11, opacity: 0.6 }}>Preview not available in browser — evaluated automatically</div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Dispatch CTA when no jobs */}
                            {codeEvalJobs.length === 0 && sub.status !== "grading" && (
                                <div style={{
                                    padding: "var(--space-5)", borderRadius: "var(--radius-lg)",
                                    border: "2px dashed var(--accent)", background: "var(--accent-dim)",
                                    textAlign: "center",
                                }}>
                                    <Sparkles size={22} style={{ margin: "0 auto var(--space-2)", color: "var(--accent)", opacity: 0.8 }} />
                                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: "var(--space-1)" }}>
                                        Ready to evaluate
                                    </div>
                                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: "var(--space-3)" }}>
                                        Click &quot;Dispatch Eval&quot; to run the approved test cases against this submission.
                                    </div>
                                    <button
                                        className="btn btn-primary btn-sm"
                                        onClick={() => setDispatchConfirm(true)}
                                        disabled={dispatchMutation.isPending}
                                    >
                                        <Play size={12} /> Dispatch Eval
                                    </button>
                                </div>
                            )}
                        </div>

                        {/* RIGHT: Eval Jobs + Grade + Audit */}
                        <div className="flex flex-col gap-4">
                            {/* Code Eval Jobs */}
                            <div className="card" style={{ padding: 0 }}>
                                <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                    <div className="flex items-center gap-2">
                                        <Play size={13} style={{ color: "var(--accent)" }} />
                                        <span style={{ fontSize: 13, fontWeight: 600 }}>Eval Jobs</span>
                                        {codeEvalJobs.length > 0 && <span className="badge badge-default" style={{ fontSize: 10 }}>{codeEvalJobs.length}</span>}
                                    </div>
                                    {hasActiveJob && (
                                        <span style={{ fontSize: 11, color: "var(--accent)", display: "flex", alignItems: "center", gap: 4 }}>
                                            <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} /> Running…
                                        </span>
                                    )}
                                </div>
                                <div style={{ padding: "var(--space-3)", overflow: "auto", maxHeight: 300 }}>
                                    {codeEvalJobs.length === 0 ? (
                                        sub.status === "grading" ? (
                                            <div style={{ textAlign: "center", padding: "var(--space-5)", fontSize: 12, color: "var(--accent)" }}>
                                                <RefreshCw size={20} style={{ margin: "0 auto var(--space-2)", animation: "spin 1s linear infinite" }} />
                                                Job queued — polling for results…
                                            </div>
                                        ) : (
                                            <div style={{ textAlign: "center", padding: "var(--space-5)", fontSize: 12, color: "var(--text-muted)" }}>
                                                No jobs yet. Dispatch an evaluation to get started.
                                            </div>
                                        )
                                    ) : codeEvalJobs.map(job => (
                                        <div key={job.id} style={{ padding: "var(--space-3)", borderRadius: "var(--radius)", border: "1px solid var(--border)", marginBottom: "var(--space-2)", background: "var(--bg-elevated)" }}>
                                            <div className="flex items-center gap-2" style={{ marginBottom: 4 }}>
                                                <span className={`badge ${JOB_STATUS_CLASS[job.status] ?? "badge-default"}`} style={{ fontSize: 10 }}>{job.status}</span>
                                                <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)", flex: 1 }}>{job.id.slice(0, 8)}</span>
                                                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{new Date(job.created_at).toLocaleTimeString()}</span>
                                            </div>
                                            <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                                                {job.language && <span>Lang: <strong>{job.language}</strong></span>}
                                                {job.entrypoint && <span>Entry: <code style={{ fontSize: 10 }}>{job.entrypoint}</code></span>}
                                            </div>
                                            {job.status === "COMPLETED" && (
                                                <div style={{ marginTop: 4, fontSize: 11, color: "var(--success)", display: "flex", alignItems: "center", gap: 4 }}>
                                                    <CheckCircle size={11} /> Completed — grade updated below
                                                </div>
                                            )}
                                            {job.status === "FAILED" && (
                                                <div style={{ marginTop: 4, fontSize: 11, color: "var(--danger)", display: "flex", alignItems: "center", gap: 4 }}>
                                                    <XCircle size={11} /> Failed
                                                    <a href={`/code-eval/jobs/${job.id}`} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", marginLeft: 6, textDecoration: "none", display: "flex", alignItems: "center", gap: 2 }}>
                                                        View logs <ExternalLink size={10} />
                                                    </a>
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Grade */}
                            <GradePanel grade={grade} maxMarks={maxMarks} />

                            {/* Audit */}
                            <AuditPanel audit={audit} />
                        </div>
                    </div>
                ) : (
                    /* ── WRITTEN ASSIGNMENT 3-PANEL LAYOUT ── */
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-4)" }}>

                        {/* Panel 1: Submission image */}
                        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                            <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-2)" }}>
                                <span style={{ fontSize: 13, fontWeight: 600 }}>Scan Image</span>
                                {isMultiPage && (
                                    <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                        <button
                                            className="btn btn-ghost btn-sm"
                                            onClick={() => setPreviewPage(Math.max(1, safePreviewPage - 1))}
                                            disabled={safePreviewPage <= 1}
                                        >
                                            Prev
                                        </button>
                                        <span style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 64, textAlign: "center" }}>
                                            Page {safePreviewPage}/{pageCount}
                                        </span>
                                        <button
                                            className="btn btn-ghost btn-sm"
                                            onClick={() => setPreviewPage(Math.min(pageCount, safePreviewPage + 1))}
                                            disabled={safePreviewPage >= pageCount}
                                        >
                                            Next
                                        </button>
                                    </div>
                                )}
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
                                        src={api.submissions.imageUrl(id, safePreviewPage)}
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
                                        <div className="empty-message">OCR hasn&apos;t run yet or produced no blocks.</div>
                                    </div>
                                ) : blocks.map((block, idx) => (
                                    <div key={idx} style={{
                                        marginBottom: "var(--space-2)", borderRadius: "var(--radius)",
                                        border: `1px solid ${editingBlock === block.index ? "var(--accent)" : block.flagged ? "rgba(245,158,11,0.4)" : "var(--border)"}`,
                                        background: editingBlock === block.index ? "var(--accent-dim)" : "var(--bg-elevated)",
                                        overflow: "hidden",
                                    }}>
                                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px var(--space-3)", borderBottom: editingBlock === block.index ? "1px solid var(--border)" : "none" }}>
                                            <div className="flex items-center gap-2">
                                                <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", width: 20 }}>#{block.index + 1}</span>
                                                {block.page !== undefined && (
                                                    <span className="badge badge-default" style={{ fontSize: 10 }}>P{block.page}</span>
                                                )}
                                                {block.flagged && <span className="badge badge-warning" style={{ fontSize: 10 }}>Flagged</span>}
                                                {block.confidence !== undefined && (
                                                    <span style={{ fontSize: 10, color: block.confidence > 0.7 ? "var(--success)" : "var(--warning)" }}>
                                                        {Math.round(block.confidence * 100)}%
                                                    </span>
                                                )}
                                            </div>
                                            {editingBlock !== block.index ? (
                                                <button className="btn btn-ghost btn-icon btn-sm" onClick={() => startEdit(block)}><Edit3 size={12} /></button>
                                            ) : (
                                                <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setEditingBlock(null)}><X size={12} /></button>
                                            )}
                                        </div>
                                        {editingBlock === block.index ? (
                                            <div style={{ padding: "var(--space-3)" }}>
                                                <textarea className="input" rows={3} value={editContent} onChange={e => setEditContent(e.target.value)} style={{ marginBottom: "var(--space-2)", fontSize: 12 }} />
                                                <input className="input" placeholder="Reason for correction…" value={editReason} onChange={e => setEditReason(e.target.value)} style={{ marginBottom: "var(--space-2)", fontSize: 12 }} />
                                                <button className="btn btn-primary btn-sm w-full" onClick={() => ocrEditMutation.mutate({ block_index: block.index, new_content: editContent.trim(), reason: editReason })} disabled={ocrEditMutation.isPending}>
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
                            <GradePanel grade={grade} maxMarks={maxMarks} />
                            <AuditPanel audit={audit} />
                        </div>
                    </div>
                )}
            </div>

            {/* ── Modals ── */}

            {/* Dispatch (first time) */}
            <ConfirmModal
                open={dispatchConfirm}
                title="Dispatch Code Evaluation"
                message="This will run the approved test cases against the submitted code. A result will be produced automatically and the grade will be updated."
                confirmText="Dispatch"
                onConfirm={() => dispatchMutation.mutate(false)}
                onCancel={() => setDispatchConfirm(false)}
                loading={dispatchMutation.isPending}
            />

            {/* Re-evaluate (force regrade on completed job) */}
            <ConfirmModal
                open={reregradeConfirm}
                variant="warning"
                title="Force Re-evaluate"
                message="This submission already has a completed eval job. Re-evaluating will create a new job and replace the current grade."
                confirmText="Re-evaluate"
                onConfirm={() => dispatchMutation.mutate(true)}
                onCancel={() => setReregradeConfirm(false)}
                loading={dispatchMutation.isPending}
            />

            {/* AI Regrade (written) */}
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

            {/* Manual Override Drawer */}
            {showOverride && (
                <div style={{ position: "fixed", inset: 0, zIndex: 200, display: "flex", justifyContent: "flex-end" }}>
                    <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.5)" }} onClick={() => setShowOverride(false)} />
                    <div style={{ position: "relative", width: 440, background: "var(--bg-card)", borderLeft: "1px solid var(--border-medium)", padding: "var(--space-6)", overflowY: "auto", display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                        <div className="flex items-center justify-between">
                            <h2 style={{ fontSize: 15, fontWeight: 700 }}><PenLine size={14} style={{ marginRight: 8, display: "inline" }} />Manual Grade Override</h2>
                            <button className="btn btn-ghost btn-sm" onClick={() => setShowOverride(false)}><X size={14} /></button>
                        </div>
                        <div style={{ padding: "var(--space-3)", borderRadius: "var(--radius)", background: "var(--warning-dim)", border: "1px solid rgba(245,158,11,0.3)", fontSize: 12, color: "var(--text-secondary)" }}>
                            ⚠ A manual override deactivates the current AI grade and creates a new <code>TA_Manual</code> entry. This action is audited.
                        </div>
                        <div className="input-group">
                            <label className="input-label">Total Score (out of {maxMarks})</label>
                            <input type="number" className="input" min={0} max={maxMarks} step={0.5} value={overrideScore} onChange={e => setOverrideScore(e.target.value)} placeholder={`0 – ${maxMarks}`} />
                        </div>
                        <div className="input-group">
                            <label className="input-label">Breakdown JSON</label>
                            <textarea
                                className={`input ${overrideJsonError ? "input-error" : ""}`}
                                rows={8} value={overrideBreakdown} onChange={e => validateBreakdown(e.target.value)}
                                style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
                                placeholder={'{ "q1": { "marks": 8, "max_marks": 10, "feedback": "Good work" } }'}
                            />
                            {overrideJsonError && <span className="input-hint" style={{ color: "var(--danger)" }}>{overrideJsonError}</span>}
                        </div>
                        <div className="input-group">
                            <label className="input-label">Reason / Notes *</label>
                            <textarea className="input" rows={3} value={overrideReason} onChange={e => setOverrideReason(e.target.value)} placeholder="e.g. AI missed marks for partial credit in Q3" />
                        </div>
                        <div className="flex gap-3" style={{ marginTop: "auto" }}>
                            <button className="btn btn-secondary flex-1" onClick={() => setShowOverride(false)}>Cancel</button>
                            <button className="btn btn-primary flex-1" onClick={() => overrideMutation.mutate()} disabled={overrideMutation.isPending || !!overrideJsonError || !overrideScore || !overrideReason.trim()}>
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
