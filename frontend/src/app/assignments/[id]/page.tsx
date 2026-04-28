"use client";
import React, { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeft, BookOpen, FileText, Code2, Globe, CheckCircle,
    XCircle, AlertTriangle, Download, RefreshCw, Send, Upload,
    Sparkles, ChevronRight, Edit3, Eye, Plus, Trash2, ListChecks,
    PenLine, Server, ChevronDown, ChevronUp,
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Assignment, Rubric, PublishValidation, SyncSummary, Submission, EnvironmentVersion, ToastVariant } from "@/lib/types";

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

function OverviewTab({ assignment, rubric, validation, onPublish, publishing, onSwitchTab, envVersions, hasApprovedTests, onUpdateAuthoringPrompt }: {
    assignment: Assignment;
    rubric: Rubric | null;
    validation: PublishValidation | null;
    onPublish: () => void;
    publishing: boolean;
    onSwitchTab: (tab: string) => void;
    envVersions: EnvironmentVersion[];
    hasApprovedTests: boolean;
    onUpdateAuthoringPrompt: (nextPrompt: string) => Promise<void>;
}) {
    const router = useRouter();
    const [editingPrompt, setEditingPrompt] = useState(false);
    const [draftPrompt, setDraftPrompt] = useState(assignment.authoring_prompt ?? assignment.description ?? "");

    // Derive checklist state from live data, not from validation.checks keys
    const readyEnv = envVersions.find(e => e.status === "ready");
    const buildingEnv = envVersions.find(e => e.status === "building");
    const envReady = !!readyEnv;
    const rubricApproved = !!(rubric?.approved);

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
                <div className="card">
                    <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-3)" }}>
                        <h3 className="section-title">Original Prompt</h3>
                        {!assignment.is_published && (
                            <button className="btn btn-ghost btn-sm" onClick={() => setEditingPrompt(v => !v)}>
                                <Edit3 size={13} /> {editingPrompt ? "Cancel" : "Edit Prompt"}
                            </button>
                        )}
                    </div>
                    {editingPrompt ? (
                        <div className="flex flex-col gap-2">
                            <textarea className="textarea" rows={8} value={draftPrompt} onChange={e => setDraftPrompt(e.target.value)} />
                            <div className="flex items-center gap-2">
                                <button className="btn btn-primary btn-sm" onClick={async () => { await onUpdateAuthoringPrompt(draftPrompt); setEditingPrompt(false); }}>
                                    Save Prompt
                                </button>
                                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Draft-only editable. Publish locks this prompt.</span>
                            </div>
                        </div>
                    ) : (
                        <div style={{ whiteSpace: "pre-wrap", marginTop: "var(--space-2)", padding: "var(--space-3)", background: "var(--bg-elevated)", borderRadius: "var(--radius)", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7 }}>
                            {(assignment.authoring_prompt ?? "").trim() || "No prompt saved for this assignment."}
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

                {/* Coding assignment checklist */}
                {assignment.has_code_question && (() => {
                    const steps = [
                        {
                            label: "Set up Environment",
                            hint: envReady
                                ? `Ready — v${readyEnv?.version_number ?? "?"}`
                                : buildingEnv
                                    ? "Building…"
                                    : "Go to Environment tab → Create",
                            tab: "coding",
                            done: envReady,
                            building: !!buildingEnv && !envReady,
                        },
                        {
                            label: "Approve test cases",
                            hint: hasApprovedTests
                                ? "Approved ✓"
                                : "Go to Test Cases tab → Generate → Approve",
                            tab: "test_cases",
                            done: hasApprovedTests,
                            building: false,
                        },
                        {
                            label: "Approve rubric",
                            hint: rubricApproved
                                ? "Approved ✓"
                                : "Go to Rubric tab → Approve",
                            tab: "rubric",
                            done: rubricApproved,
                            building: false,
                        },
                        {
                            label: "Publish",
                            hint: assignment.is_published
                                ? `Published ${assignment.published_at ? new Date(assignment.published_at).toLocaleDateString() : ""}`
                                : "Click Publish when steps above are done",
                            tab: null,
                            done: assignment.is_published,
                            building: false,
                        },
                    ];
                    const completedCount = steps.filter(s => s.done).length;
                    return (
                        <div className="card" style={{ borderColor: "rgba(59,130,246,0.3)", borderWidth: 2 }}>
                            <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-3)" }}>
                                <h3 className="section-title">
                                    <Sparkles size={13} style={{ display: "inline", marginRight: 6, color: "var(--accent)" }} />
                                    Setup Checklist
                                </h3>
                                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                    {completedCount}/{steps.length}
                                </span>
                            </div>
                            {/* Progress bar */}
                            <div style={{ height: 3, background: "var(--border)", borderRadius: 4, marginBottom: "var(--space-4)", overflow: "hidden" }}>
                                <div style={{ height: "100%", width: `${(completedCount / steps.length) * 100}%`, background: completedCount === steps.length ? "var(--success)" : "var(--accent)", borderRadius: 4, transition: "width 0.4s ease" }} />
                            </div>
                            <div className="flex flex-col gap-1">
                                {steps.map(({ label, hint, tab, done, building }, i) => (
                                    <div key={i}
                                        onClick={() => tab && onSwitchTab(tab)}
                                        style={{
                                            display: "flex", alignItems: "center", gap: "var(--space-2)",
                                            padding: "var(--space-2) var(--space-1)", borderRadius: "var(--radius)",
                                            cursor: tab ? "pointer" : "default", transition: "background 0.1s",
                                        }}
                                        onMouseEnter={e => { if (tab) (e.currentTarget as HTMLElement).style.background = "var(--bg-elevated)"; }}
                                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = ""; }}>
                                        {/* Step indicator */}
                                        <div style={{
                                            width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
                                            background: done ? "var(--success)" : building ? "var(--warning)" : "var(--bg-elevated)",
                                            border: `2px solid ${done ? "var(--success)" : building ? "var(--warning)" : "var(--border-medium)"}`,
                                            display: "flex", alignItems: "center", justifyContent: "center",
                                            fontSize: 9, color: "#fff", fontWeight: 700,
                                            animation: building ? "pulse 1.5s ease-in-out infinite" : undefined,
                                        }}>
                                            {done ? "✓" : building ? "⋯" : i + 1}
                                        </div>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontSize: 12, fontWeight: 500, color: done ? "var(--text-muted)" : "var(--text-primary)", textDecoration: done ? "line-through" : undefined }}>
                                                {label}
                                            </div>
                                            <div style={{ fontSize: 10, color: done ? "var(--success)" : building ? "var(--warning)" : "var(--text-muted)", marginTop: 1 }}>
                                                {hint}
                                            </div>
                                        </div>
                                        {tab && !done && <ChevronRight size={12} style={{ color: "var(--text-muted)", flexShrink: 0 }} />}
                                    </div>
                                ))}
                            </div>
                        </div>
                    );
                })()}
            </div>
        </div>
    );
}



// ── Rubric validation ────────────────────────────────────────────────────────

type RubricWarning = { type: "error" | "warning"; message: string };

function validateRubricJson(contentJson: Record<string, unknown>, assignmentMaxMarks: number): RubricWarning[] {
    const warnings: RubricWarning[] = [];
    const questions = (contentJson?.questions ?? []) as Array<{
        id?: string; description?: string; max_marks?: number;
        criteria?: Array<{ marks?: number }>;
    }>;
    if (questions.length === 0) {
        warnings.push({ type: "warning", message: "No questions defined in this rubric." });
        return warnings;
    }
    let totalQMarks = 0;
    questions.forEach((q, qi) => {
        const qMax = q.max_marks ?? 0;
        totalQMarks += qMax;
        const criteria = Array.isArray(q.criteria) ? q.criteria : [];
        const criteriaSum = criteria.reduce((s, c) => s + (c.marks ?? 0), 0);
        if (criteria.length === 0) {
            warnings.push({ type: "warning", message: `Q${qi + 1}: No criteria defined.` });
        } else if (Math.abs(criteriaSum - qMax) > 0.01) {
            const diff = criteriaSum - qMax;
            warnings.push({
                type: "error",
                message: `Q${qi + 1} "${q.description || q.id || ""}": criteria sum ${criteriaSum} ≠ max_marks ${qMax} (${diff > 0 ? "+" : ""}${diff.toFixed(1)}).`,
            });
        }
    });
    if (Math.abs(totalQMarks - assignmentMaxMarks) > 0.01) {
        const diff = totalQMarks - assignmentMaxMarks;
        warnings.push({
            type: "error",
            message: `Question totals sum to ${totalQMarks} but assignment max marks is ${assignmentMaxMarks} (${diff > 0 ? "+" : ""}${diff.toFixed(1)}).`,
        });
    }
    return warnings;
}

function RubricValidationBanner({ warnings }: { warnings: RubricWarning[] }) {
    if (warnings.length === 0) return null;
    const hasErrors = warnings.some(w => w.type === "error");
    return (
        <div style={{
            borderRadius: "var(--radius)", marginBottom: "var(--space-3)",
            border: `1px solid ${hasErrors ? "rgba(239,68,68,0.35)" : "rgba(245,158,11,0.35)"}`,
            background: hasErrors ? "var(--danger-dim)" : "var(--warning-dim)",
            padding: "var(--space-3) var(--space-4)",
        }}>
            <div className="flex items-center gap-2" style={{ marginBottom: warnings.length > 1 ? "var(--space-1)" : 0 }}>
                <AlertTriangle size={13} style={{ color: hasErrors ? "var(--danger)" : "var(--warning)", flexShrink: 0 }} />
                <span style={{ fontSize: 12, fontWeight: 600, color: hasErrors ? "var(--danger)" : "var(--warning)" }}>
                    {hasErrors ? "Validation errors — fix before approving" : "Warnings"}
                </span>
            </div>
            {warnings.map((w, i) => (
                <div key={i} style={{ fontSize: 11, color: "var(--text-secondary)", paddingLeft: "var(--space-5)", marginTop: 2 }}>
                    • {w.message}
                </div>
            ))}
        </div>
    );
}

// ── Rubric helpers ────────────────────────────────────────────────────────────

type RubricQuestion = {
    id?: string;
    description?: string;
    max_marks?: number;
    criteria?: Array<{ step: string; marks: number; partial_credit?: boolean }>;
};

function RubricQuestionCard({ q, index, onRefresh, actor, toast }: {
    q: RubricQuestion;
    index: number;
    onRefresh: () => void;
    actor: string;
    toast: (variant: ToastVariant, title: string, msg?: string) => void;
}) {
    const [open, setOpen] = useState(false);

    const criteria = Array.isArray(q.criteria) ? q.criteria : [];
    const totalCriteria = criteria.reduce((s, c) => s + (c.marks || 0), 0);

    return (
        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
            <div
                style={{ padding: "var(--space-3) var(--space-4)", background: "var(--bg-elevated)", display: "flex", alignItems: "center", gap: "var(--space-3)", cursor: "pointer" }}
                onClick={() => setOpen(o => !o)}
            >
                <div style={{ minWidth: 28, height: 28, borderRadius: "var(--radius-sm)", background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "var(--accent)", flexShrink: 0 }}>
                    Q{index + 1}
                </div>
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{q.description || q.id || `Question ${index + 1}`}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{criteria.length} criteria · {totalCriteria} / {q.max_marks ?? "?"} marks allocated</div>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-secondary)", marginRight: "var(--space-2)" }}>{q.max_marks ?? "?"} marks</div>
                {open ? <ChevronUp size={14} style={{ color: "var(--text-muted)", flexShrink: 0 }} /> : <ChevronDown size={14} style={{ color: "var(--text-muted)", flexShrink: 0 }} />}
            </div>

            {open && (
                <div style={{ padding: "var(--space-3) var(--space-4)", borderTop: "1px solid var(--border)" }}>
                    {criteria.length === 0 ? (
                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No criteria defined.</div>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {criteria.map((c, ci) => (
                                <div key={ci} style={{ display: "flex", alignItems: "flex-start", gap: "var(--space-3)", padding: "var(--space-2) var(--space-3)", borderRadius: "var(--radius-sm)", background: "var(--bg-surface)", border: "1px solid var(--border)" }}>
                                    <div style={{ width: 20, height: 20, borderRadius: "50%", background: "var(--bg-elevated)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--text-muted)", flexShrink: 0, marginTop: 1 }}>{ci + 1}</div>
                                    <div style={{ flex: 1, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>{c.step}</div>
                                    <div style={{ flexShrink: 0, fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{c.marks}m</div>
                                    {c.partial_credit && <span style={{ fontSize: 10, color: "var(--success)", background: "var(--success-dim)", borderRadius: "var(--radius-sm)", padding: "1px 5px", flexShrink: 0 }}>partial</span>}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ── Rubric Tab ─────────────────────────────────────────────────────────────

function RubricTab({ assignment, onRefresh }: {
    assignment: Assignment;
    onRefresh: () => void;
}) {
    const { actor } = useAuth();
    const { toast } = useToast();
    const qc = useQueryClient();
    const [genMode, setGenMode] = useState<"ai" | "nl" | "json">("ai");
    const [assignmentText, setAssignmentText] = useState("");
    const [nlText, setNlText] = useState("");
    const [manualJson, setManualJson] = useState("");
    const [generating, setGenerating] = useState(false);
    const [showRawId, setShowRawId] = useState<string | null>(null);
    const [editRubricId, setEditRubricId] = useState<string | null>(null);
    const [editJson, setEditJson] = useState("");

    const { data: rubrics = [], refetch } = useQuery({
        queryKey: ["rubrics-all", assignment.id],
        queryFn: () => api.rubrics.listAll(assignment.id),
    });
    const activeRubric = rubrics.find(r => r.approved) ?? rubrics[0] ?? null;

    const refresh = () => { refetch(); onRefresh(); };

    const approveMutation = useMutation({
        mutationFn: (rubricId: string) => {
            const r = rubrics.find(rb => rb.id === rubricId);
            if (r) {
                const errs = validateRubricJson(r.content_json ?? {}, assignment.max_marks).filter(w => w.type === "error");
                if (errs.length > 0) throw new Error(errs.map(e => e.message).join(" | "));
            }
            return api.rubrics.approve(rubricId, actor ?? "ta");
        },
        onSuccess: () => { toast("success", "Rubric approved!"); refresh(); },
        onError: (e: Error) => toast("error", "Approval failed", e.message),
    });

    const deleteMutation = useMutation({
        mutationFn: (rubricId: string) => api.rubrics.remove(rubricId),
        onSuccess: () => { toast("success", "Rubric version deleted"); refresh(); },
        onError: (e: Error) => toast("error", "Delete failed", e.message),
    });

    const saveJsonMutation = useMutation({
        mutationFn: ({ id, json }: { id: string; json: string }) => {
            const parsed = JSON.parse(json);
            const errs = validateRubricJson(parsed, assignment.max_marks).filter(w => w.type === "error");
            if (errs.length > 0) throw new Error(errs.map(e => e.message).join(" | "));
            return api.rubrics.update(id, parsed);
        },
        onSuccess: () => { toast("success", "Rubric updated — re-approval required"); setEditRubricId(null); refresh(); },
        onError: (e: Error) => toast("error", "Save failed", e.message),
    });

    const createManualMutation = useMutation({
        mutationFn: () => {
            const parsed = JSON.parse(manualJson);
            return api.rubrics.create(assignment.id, parsed);
        },
        onSuccess: () => { toast("success", "Manual rubric saved & approved!"); setManualJson(""); refresh(); },
        onError: (e: Error) => toast("error", "Save failed", e.message),
    });

    const doGenerate = async () => {
        if (genMode === "ai" && !assignmentText.trim()) { toast("warning", "Describe the assignment first"); return; }
        if (genMode === "nl" && !nlText.trim()) { toast("warning", "Enter your rubric description first"); return; }
        if (genMode === "json") { createManualMutation.mutate(); return; }
        setGenerating(true);
        try {
            if (genMode === "ai") {
                await api.rubrics.generate(assignment.id, assignmentText);
                toast("success", "Rubric generated!", "Review and approve it below.");
            } else {
                await api.rubrics.encodeNaturalLanguage(assignment.id, nlText);
                toast("success", "Rubric encoded!", "Review and approve it below.");
            }
            refresh();
        } catch (e: unknown) {
            toast("error", "Failed", (e as Error).message);
        } finally {
            setGenerating(false);
        }
    };

    const questions: RubricQuestion[] = (activeRubric?.content_json?.questions ?? []) as RubricQuestion[];
    const scoringPolicy = activeRubric?.content_json?.scoring_policy as Record<string, unknown> | undefined;
    const codingPolicy = scoringPolicy?.coding as { rubric_weight?: number; testcase_weight?: number } | undefined;

    return (
        <div className="flex flex-col gap-6">
            {/* Generator panel */}
            <div className="card">
                <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>
                    <Sparkles size={14} style={{ display: "inline", marginRight: 6, color: "var(--accent)" }} />
                    Create / Generate Rubric
                </h3>

                {/* Mode tabs */}
                <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-4)", borderBottom: "1px solid var(--border)", paddingBottom: "var(--space-3)" }}>
                    {([
                        { id: "ai" as const, label: "AI from Assignment", icon: Sparkles },
                        { id: "nl" as const, label: "Natural Language", icon: PenLine },
                        { id: "json" as const, label: "Manual JSON", icon: Edit3 },
                    ] as const).map(({ id, label, icon: Icon }) => (
                        <button key={id} onClick={() => setGenMode(id)}
                            className={`btn btn-sm ${genMode === id ? "btn-primary" : "btn-ghost"}`}>
                            <Icon size={12} /> {label}
                        </button>
                    ))}
                </div>

                {genMode === "ai" && (
                    <div className="flex flex-col gap-3">
                        <div className="input-group">
                            <label className="input-label">Describe Your Assignment</label>
                            <textarea className="input" rows={6}
                                placeholder={`Paste the full question paper, describe the problems, or paste a model answer.\nThe AI will infer how many questions exist and build a marking scheme for each.\n\nExample:\n  Q1. Explain Big-O notation with examples. (10 marks)\n  Q2. Write a binary search algorithm. (15 marks)`}
                                value={assignmentText} onChange={e => setAssignmentText(e.target.value)} />
                            <span className="input-hint">Works for single or multi-question assignments. The AI infers structure automatically.</span>
                        </div>
                        {assignment.has_code_question && (
                            <div style={{ fontSize: 12, color: "var(--text-muted)", background: "var(--accent-dim)", borderRadius: "var(--radius)", padding: "var(--space-3)" }}>
                                <strong>Coding assignment:</strong> The AI will also suggest rubric vs testcase weightings in the scoring policy.
                            </div>
                        )}
                    </div>
                )}

                {genMode === "nl" && (
                    <div className="input-group">
                        <label className="input-label">Describe Your Rubric in Plain English</label>
                        <textarea className="input" rows={5}
                            placeholder={`e.g. "5 marks for correct output, 3 for clean code, 2 for edge case handling"`
                                + `\nOr: "Q1 gets 10 marks — 4 for defining the concept, 3 for an example, 3 for edge cases."`
                                + `\n     "Q2 gets 15 marks — binary search implementation only."`}
                            value={nlText} onChange={e => setNlText(e.target.value)} />
                        <span className="input-hint">The AI will encode this into the structured rubric format. You can review and edit before approving.</span>
                    </div>
                )}

                {genMode === "json" && (
                    <div className="input-group">
                        <label className="input-label">Rubric JSON</label>
                        <textarea className="input" rows={10} style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
                            placeholder={JSON.stringify({ questions: [{ id: "Q1", description: "...", max_marks: 10, criteria: [{ step: "Correct output", marks: 5, partial_credit: true }] }] }, null, 2)}
                            value={manualJson} onChange={e => setManualJson(e.target.value)} />
                        <span className="input-hint">Manual rubrics are immediately approved.</span>
                    </div>
                )}

                <button className="btn btn-primary" style={{ marginTop: "var(--space-4)" }}
                    onClick={doGenerate} disabled={generating || createManualMutation.isPending}>
                    {generating
                        ? <><RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> {genMode === "ai" ? "Generating…" : "Encoding…"}</>
                        : genMode === "json"
                            ? <><Plus size={13} /> Save Manual Rubric</>
                            : genMode === "nl"
                                ? <><PenLine size={13} /> Encode with AI</>
                                : <><Sparkles size={13} /> Generate Rubric</>}
                </button>
            </div>

            {/* All rubric versions */}
            {rubrics.length > 0 && (
                <div className="card">
                    <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>Rubric Versions ({rubrics.length})</h3>
                    <div className="flex flex-col gap-3">
                        {rubrics.map((r, vi) => {
                            const isEditing = editRubricId === r.id;
                            const qList: RubricQuestion[] = (r.content_json?.questions ?? []) as RubricQuestion[];
                            const sp = r.content_json?.scoring_policy as Record<string, unknown> | undefined;
                            const cp = sp?.coding as { rubric_weight?: number; testcase_weight?: number } | undefined;
                            const vWarnings = validateRubricJson(r.content_json ?? {}, assignment.max_marks);
                            const vErrors = vWarnings.filter(w => w.type === "error");
                            return (
                                <div key={r.id} style={{ border: `2px solid ${r.approved ? "rgba(34,197,94,0.4)" : vErrors.length ? "rgba(239,68,68,0.4)" : "var(--border)"}`, borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
                                    {/* Version header */}
                                    <div style={{ padding: "var(--space-3) var(--space-4)", background: r.approved ? "var(--success-dim)" : "var(--bg-elevated)", display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                                        <div style={{ flex: 1 }}>
                                            <div className="flex items-center gap-2">
                                                <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)" }}>Version {rubrics.length - vi}</span>
                                                <span className={`badge ${r.approved ? "badge-success" : "badge-warning"}`} style={{ fontSize: 10 }}>{r.approved ? "✓ Approved" : "Draft"}</span>
                                                <span className="badge badge-default" style={{ fontSize: 10 }}>{r.source === "ai_generated" ? "AI" : "Manual"}</span>
                                                {r.approved_by && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>by {r.approved_by}</span>}
                                                {vErrors.length > 0 && <span className="badge badge-danger" style={{ fontSize: 10 }}><AlertTriangle size={9} style={{ display: "inline", marginRight: 2 }} />{vErrors.length} error{vErrors.length > 1 ? "s" : ""}</span>}
                                            </div>
                                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                                                {qList.length} question{qList.length !== 1 ? "s" : ""}
                                                {cp && ` · Rubric ${cp.rubric_weight}% / Tests ${cp.testcase_weight}%`}
                                                {r.created_at && ` · ${new Date(r.created_at).toLocaleString()}`}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {!r.approved && (
                                                <button className="btn btn-success btn-sm"
                                                    onClick={() => approveMutation.mutate(r.id)}
                                                    disabled={approveMutation.isPending || vErrors.length > 0}
                                                    title={vErrors.length > 0 ? "Fix validation errors first" : "Approve this rubric"}>
                                                    <CheckCircle size={12} /> Approve{vErrors.length > 0 ? " (blocked)" : ""}
                                                </button>
                                            )}
                                            <button className="btn btn-ghost btn-sm"
                                                onClick={() => { setEditRubricId(isEditing ? null : r.id); setEditJson(JSON.stringify(r.content_json, null, 2)); }}>
                                                <Edit3 size={12} /> {isEditing ? "Cancel" : "Edit JSON"}
                                            </button>
                                            <button className="btn btn-ghost btn-sm"
                                                onClick={() => setShowRawId(showRawId === r.id ? null : r.id)}>
                                                <Eye size={12} /> {showRawId === r.id ? "Hide" : "Raw"}
                                            </button>
                                            <button className="btn btn-ghost btn-sm" style={{ color: "var(--danger)" }}
                                                onClick={() => deleteMutation.mutate(r.id)}
                                                disabled={deleteMutation.isPending}>
                                                <Trash2 size={12} />
                                            </button>
                                        </div>
                                    </div>

                                    {/* Edit JSON panel */}
                                    {isEditing && (() => {
                                        let liveWarnings: RubricWarning[] = [];
                                        try {
                                            const lp = JSON.parse(editJson);
                                            liveWarnings = validateRubricJson(lp, assignment.max_marks);
                                        } catch { liveWarnings = [{ type: "error", message: "Invalid JSON — cannot parse." }]; }
                                        return (
                                            <div style={{ padding: "var(--space-4)", borderTop: "1px solid var(--border)" }}>
                                                <textarea className="input" rows={12} style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
                                                    value={editJson} onChange={e => setEditJson(e.target.value)} />
                                                <RubricValidationBanner warnings={liveWarnings} />
                                                <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-3)" }}>
                                                    <button className="btn btn-primary btn-sm"
                                                        onClick={() => saveJsonMutation.mutate({ id: r.id, json: editJson })}
                                                        disabled={saveJsonMutation.isPending || liveWarnings.some(w => w.type === "error")}>
                                                        Save Changes
                                                    </button>
                                                    <button className="btn btn-ghost btn-sm" onClick={() => setEditRubricId(null)}>Cancel</button>
                                                </div>
                                                <div style={{ fontSize: 11, color: "var(--warning)", marginTop: "var(--space-2)" }}>Saving will reset approval — you must re-approve after editing.</div>
                                            </div>
                                        );
                                    })()}

                                    {/* Raw JSON panel */}
                                    {showRawId === r.id && !isEditing && (
                                        <div className="code-block" style={{ maxHeight: 300, overflow: "auto", margin: "var(--space-3)", borderRadius: "var(--radius)" }}>
                                            {JSON.stringify(r.content_json, null, 2)}
                                        </div>
                                    )}

                                    {/* Formatted questions */}
                                    {showRawId !== r.id && !isEditing && qList.length > 0 && (
                                        <div style={{ padding: "var(--space-3)", display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                                            <RubricValidationBanner warnings={vWarnings} />
                                            {qList.map((q, qi) => (
                                                <RubricQuestionCard key={qi} q={q} index={qi} onRefresh={refresh} actor={actor ?? "ta"} toast={toast} />
                                            ))}
                                            {cp && (
                                                <div style={{ marginTop: "var(--space-2)", padding: "var(--space-2) var(--space-3)", background: "var(--accent-dim)", borderRadius: "var(--radius)", fontSize: 12, color: "var(--text-secondary)" }}>
                                                    <Server size={12} style={{ display: "inline", marginRight: 4 }} />
                                                    Scoring: {cp.rubric_weight}% rubric · {cp.testcase_weight}% test cases
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {rubrics.length === 0 && (
                <div className="empty-state">
                    <BookOpen size={40} className="empty-icon" />
                    <div className="empty-title">No rubric yet</div>
                    <div className="empty-message">Generate one above or paste your rubric in JSON / natural language.</div>
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

function SubmissionsTab({ assignmentId, maxMarks }: { assignmentId: string; maxMarks: number }) {
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
                                {subs.map(sub => {
                                    const score = (sub as Submission & { total_score?: number }).total_score;
                                    return (
                                        <tr key={sub.id} className="clickable" onClick={() => router.push(`/submissions/${sub.id}`)}>
                                            <td>
                                                <div style={{ fontWeight: 500, fontSize: 13 }}>{sub.student_name || sub.student_id}</div>
                                                <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{sub.student_id}</div>
                                            </td>
                                            <td><span className={`badge ${SUB_STATUS_CLASS[sub.status]}`}>{sub.status.replace(/_/g, " ")}</span></td>
                                            <td style={{ fontSize: 13, fontWeight: score != null ? 600 : 400, color: score != null ? "var(--text-primary)" : "var(--text-muted)" }}>
                                                {score != null ? `${score} / ${maxMarks}` : "—"}
                                            </td>
                                            <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                                {new Date(sub.created_at).toLocaleDateString()}
                                            </td>
                                            <td><ChevronRight size={14} style={{ color: "var(--text-muted)" }} /></td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}

// ── Classroom Tab ───────────────────────────────────────────────


function ClassroomTab({ assignment }: { assignment: Assignment }) {
    const qc = useQueryClient();
    const { toast } = useToast();
    const [courseIdInput, setCourseIdInput] = useState(assignment.course_id || "");
    const [courseworkIdInput, setCourseworkIdInput] = useState(assignment.classroom_id || "");
    const [publishOnCreate, setPublishOnCreate] = useState(true);
    const [forceReingest, setForceReingest] = useState(false);

    const { data: status } = useQuery({
        queryKey: ["classroom-status", assignment.id],
        queryFn: () => api.classroom.status(assignment.id),
    });
    const { data: authStatus } = useQuery({
        queryKey: ["classroom-auth"],
        queryFn: api.classroom.authStatus,
    });
    const { data: courseworkList } = useQuery({
        queryKey: ["classroom-coursework-list", assignment.id, courseIdInput],
        queryFn: () => api.classroom.listCoursework(courseIdInput.trim()),
        enabled: !!courseIdInput.trim() && !!authStatus?.authenticated,
    });

    const refreshAll = () => {
        qc.invalidateQueries({ queryKey: ["classroom-status", assignment.id] });
        qc.invalidateQueries({ queryKey: ["assignment", assignment.id] });
        qc.invalidateQueries({ queryKey: ["submissions-tab", assignment.id] });
        qc.invalidateQueries({ queryKey: ["classroom-auth"] });
    };

    const reconnectClassroom = useMutation({
        mutationFn: (forceReauth: boolean) => api.classroom.generateToken(forceReauth),
        onSuccess: (s) => {
            if (s.ready) {
                toast("success", "Classroom connected", "Token refreshed with required scopes.");
            } else {
                const missing = (s.missing_scopes ?? []).length;
                toast("warning", "Reconnect completed", missing ? `${missing} required scopes still missing.` : "Token updated.");
            }
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Reconnect failed", e.message),
    });

    const linkCoursework = useMutation({
        mutationFn: () => api.classroom.linkCoursework(assignment.id, {
            course_id: courseIdInput.trim(),
            coursework_id: courseworkIdInput.trim(),
        }),
        onSuccess: () => {
            toast("success", "Classroom linked", "Coursework linked to this assignment.");
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Link failed", e.message),
    });

    const createCoursework = useMutation({
        mutationFn: () => api.classroom.createCoursework(assignment.id, {
            course_id: courseIdInput.trim(),
            publish: publishOnCreate,
        }),
        onSuccess: (res) => {
            setCourseworkIdInput(res.coursework_id);
            toast("success", "Coursework created", `Created and linked coursework ${res.coursework_id}.`);
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Create coursework failed", e.message),
    });

    const updateCoursework = useMutation({
        mutationFn: () => api.classroom.updateCoursework(assignment.id, {
            course_id: courseIdInput.trim(),
            title: assignment.title,
            description: assignment.description ?? undefined,
            max_points: assignment.max_marks,
            publish: assignment.is_published,
        }),
        onSuccess: () => {
            toast("success", "Coursework updated", "Classroom coursework updated from AMGS assignment.");
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Update coursework failed", e.message),
    });

    const ingest = useMutation({
        mutationFn: () => api.classroom.ingest(assignment.id, {
            course_id: courseIdInput.trim(),
            coursework_id: courseworkIdInput.trim() || assignment.classroom_id || "",
            force_reingest: forceReingest,
        }),
        onSuccess: (s) => {
            toast("success", "Ingested", `${s.ingested} new submissions, ${s.skipped} skipped.`);
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Ingest failed", e.message),
    });
    const syncDraft = useMutation({
        mutationFn: () => api.classroom.syncDraft(assignment.id),
        onSuccess: (s) => {
            toast("success", "Draft synced", `${s.pushed} grades pushed, ${s.skipped} skipped.`);
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Sync failed", e.message),
    });
    const release = useMutation({
        mutationFn: () => api.classroom.release(assignment.id),
        onSuccess: (s) => {
            toast("success", "Grades released", `${s.released} students notified, ${s.skipped} skipped.`);
            refreshAll();
        },
        onError: (e: Error) => toast("error", "Release failed", e.message),
    });

    const syncReady = (status?.sync_missing?.length ?? 0) === 0 && !!(courseworkIdInput.trim() || assignment.classroom_id);

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
                        {!!authStatus?.authenticated && (
                            <div style={{ fontSize: 12, color: authStatus?.ready ? "var(--success)" : "var(--warning)", marginTop: 4 }}>
                                {authStatus?.ready
                                    ? "Ready for create/sync/release actions."
                                    : (authStatus?.has_required_scopes
                                        ? "Scopes are complete; token/session needs refresh."
                                        : `Missing required scopes: ${(authStatus?.missing_scopes ?? []).length}`)}
                            </div>
                        )}
                        {!!authStatus?.authenticated && authStatus?.expired && (
                            <div style={{ fontSize: 12, color: "var(--warning)", marginTop: 4 }}>
                                Token is expired; reconnect if the next Classroom action fails.
                            </div>
                        )}
                        {!authStatus?.authenticated && authStatus?.reason && (
                            <div style={{ fontSize: 12, color: "var(--warning)", marginTop: 4 }}>
                                {String(authStatus.reason)}
                            </div>
                        )}
                    </div>
                    <div className="flex items-center gap-2" style={{ marginLeft: "auto" }}>
                        <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => reconnectClassroom.mutate(false)}
                            disabled={reconnectClassroom.isPending}
                        >
                            {reconnectClassroom.isPending ? "Opening OAuth…" : "Reconnect"}
                        </button>
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => reconnectClassroom.mutate(true)}
                            disabled={reconnectClassroom.isPending}
                            title="Forces full Google consent screen and token replacement"
                        >
                            {reconnectClassroom.isPending ? "Please finish in browser…" : "Force Re-auth"}
                        </button>
                    </div>
                </div>
            </div>

            <div className="card">
                <h3 className="section-title" style={{ marginBottom: "var(--space-4)" }}>Coursework Link</h3>
                <div className="flex flex-col gap-3">
                    <div className="input-group">
                        <label className="input-label">Classroom Course ID</label>
                        <input className="input" value={courseIdInput} onChange={e => setCourseIdInput(e.target.value)} placeholder="e.g. 765432109876" />
                    </div>
                    <div className="input-group">
                        <label className="input-label">Classroom Coursework ID</label>
                        <input className="input" value={courseworkIdInput} onChange={e => setCourseworkIdInput(e.target.value)} placeholder="Existing coursework id (optional if creating new)" />
                    </div>
                    <div className="flex items-center gap-2">
                        <button className="btn btn-secondary" onClick={() => linkCoursework.mutate()} disabled={linkCoursework.isPending || !courseIdInput.trim() || !courseworkIdInput.trim() || !authStatus?.authenticated}>
                            {linkCoursework.isPending ? "Linking…" : "Link Existing Coursework"}
                        </button>
                        <button className="btn btn-primary" onClick={() => createCoursework.mutate()} disabled={createCoursework.isPending || !courseIdInput.trim() || !authStatus?.authenticated || !authStatus?.has_required_scopes}>
                            {createCoursework.isPending ? "Creating…" : "Create Coursework From Assignment"}
                        </button>
                        <button className="btn btn-ghost" onClick={() => updateCoursework.mutate()} disabled={updateCoursework.isPending || !courseIdInput.trim() || !assignment.classroom_id || !authStatus?.authenticated || !authStatus?.has_required_scopes}>
                            {updateCoursework.isPending ? "Updating…" : "Update Linked Coursework"}
                        </button>
                    </div>
                    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-muted)" }}>
                        <input type="checkbox" checked={publishOnCreate} onChange={e => setPublishOnCreate(e.target.checked)} />
                        Publish immediately when creating coursework
                    </label>
                    {!!courseworkList?.items?.length && (
                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                            Recent Coursework: {courseworkList.items.slice(0, 5).map(cw => `${cw.title} (${cw.id})`).join(" | ")}
                        </div>
                    )}
                </div>
            </div>

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
                <div style={{ fontSize: 12, color: syncReady ? "var(--success)" : "var(--warning)", marginBottom: "var(--space-3)" }}>
                    {syncReady
                        ? "Sync checks passed. Grade push is enabled."
                        : `Sync checks pending: ${(status?.sync_missing ?? ["link coursework"]).join(", ")}`}
                </div>
                <div className="flex flex-col gap-3">
                    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-muted)" }}>
                        <input type="checkbox" checked={forceReingest} onChange={e => setForceReingest(e.target.checked)} />
                        Force re-ingest (replace existing ingested files for matching students)
                    </label>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-3)" }}>
                        <button
                            className="btn btn-secondary"
                            onClick={() => ingest.mutate()}
                            disabled={ingest.isPending || !authStatus?.authenticated || !authStatus?.has_required_scopes || !courseIdInput.trim() || !(courseworkIdInput.trim() || assignment.classroom_id)}
                        >
                            <Download size={13} />
                            {ingest.isPending ? "Pulling…" : "Pull Submissions"}
                        </button>
                        <button
                            className="btn btn-secondary"
                            onClick={() => syncDraft.mutate()}
                            disabled={syncDraft.isPending || !authStatus?.authenticated || !authStatus?.has_required_scopes || !syncReady}
                        >
                            <Send size={13} />
                            {syncDraft.isPending ? "Pushing…" : "Push Draft Grades"}
                        </button>
                        <button
                            className="btn btn-success"
                            onClick={() => release.mutate()}
                            disabled={release.isPending || !authStatus?.authenticated || !authStatus?.has_required_scopes || !syncReady}
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

// ── Environment Tab ──────────────────────────────────────────────────────
const PROFILE_KEYS = ["python-3.11", "python-3.10", "node-18", "java-17", "cpp-17", "custom"];
const PROFILE_DESCRIPTIONS: Record<string, string> = {
    "python-3.11": "Python 3.11 sandbox with standard data-science libs",
    "python-3.10": "Python 3.10 sandbox",
    "node-18": "Node.js 18 LTS sandbox",
    "java-17": "OpenJDK 17 sandbox",
    "cpp-17": "GCC 12 C++17 sandbox",
    "custom": "Custom environment defined via spec_json",
};

function EnvironmentTab({ assignment, onEnvSelected }: {
    assignment: Assignment;
    onEnvSelected: (envId: string | null) => void;
}) {
    const { actor } = useAuth();
    const { toast } = useToast();
    const qc = useQueryClient();

    const { data: envVersions = [], isLoading } = useQuery({
        queryKey: ["env-versions", assignment.id],
        queryFn: () => api.codeEval.environments.list({ assignment_id: assignment.id }),
    });

    const { data: allEnvVersions = [] } = useQuery({
        queryKey: ["env-versions-all"],
        queryFn: () => api.codeEval.environments.list(),
        enabled: envVersions.length === 0,
    });

    const [selectedId, setSelectedId] = useState<string>("");
    const [buildingId, setBuildingId] = useState<string | null>(null);
    const [showCreateForm, setShowCreateForm] = useState(false);
    const [newEnvForm, setNewEnvForm] = useState({
        profileKey: "python-3.11",
        reuseMode: "course_reuse_with_assignment_overrides",
        specJson: "{}",
        specError: null as string | null,
    });

    const displayVersions = envVersions.length > 0 ? envVersions : allEnvVersions;

    const buildMutation = useMutation({
        mutationFn: (id: string) => {
            setBuildingId(id);
            return api.codeEval.environments.build(id, actor ?? "ta");
        },
        onSuccess: () => {
            toast("success", "Build triggered", "Environment is building...");
            qc.invalidateQueries({ queryKey: ["env-versions"] });
            setBuildingId(null);
        },
        onError: (e: Error) => { toast("error", "Build failed", e.message); setBuildingId(null); },
    });

    const createMutation = useMutation({
        mutationFn: () => {
            let spec: Record<string, unknown>;
            try { spec = JSON.parse(newEnvForm.specJson); } catch { throw new Error("spec_json is not valid JSON"); }
            return api.codeEval.environments.create({
                course_id: assignment.course_id,
                assignment_id: assignment.id,
                profile_key: newEnvForm.profileKey,
                reuse_mode: newEnvForm.reuseMode,
                spec_json: spec,
                created_by: actor ?? "instructor",
            });
        },
        onSuccess: (env) => {
            toast("success", "Environment created!", "Now build it to activate.");
            qc.invalidateQueries({ queryKey: ["env-versions", assignment.id] });
            qc.invalidateQueries({ queryKey: ["env-versions-all"] });
            setShowCreateForm(false);
            setSelectedId(env.id);
            onEnvSelected(env.id);
        },
        onError: (e: Error) => toast("error", "Create failed", e.message),
    });

    const statusColor: Record<string, string> = {
        ready: "var(--success)", building: "var(--warning)", failed: "var(--danger)",
        pending: "var(--text-muted)", inactive: "var(--text-muted)",
    };

    const statusClass: Record<string, string> = {
        ready: "badge-success", building: "badge-warning", failed: "badge-danger",
        pending: "badge-default", inactive: "badge-default",
    };

    return (
        <div className="flex flex-col gap-6">
            {/* Header + create */}
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="section-title">Code Evaluation Environment</h3>
                    <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                        Select or create an environment that will execute test cases for this coding assignment.
                    </p>
                </div>
                <button className="btn btn-primary btn-sm" onClick={() => setShowCreateForm(s => !s)}>
                    <Plus size={13} /> New Environment
                </button>
            </div>

            {/* Create form */}
            {showCreateForm && (() => {
                const LANG_OPTS = [
                    { value: "python", label: "Python", defaultEp: "solution.py" },
                    { value: "javascript", label: "JavaScript", defaultEp: "solution.js" },
                    { value: "java", label: "Java", defaultEp: "Main.java" },
                    { value: "cpp", label: "C++", defaultEp: "solution.cpp" },
                    { value: "c", label: "C", defaultEp: "solution.c" },
                ];
                const lang = (newEnvForm as typeof newEnvForm & { language?: string; entrypoint?: string }).language ?? "python";
                const ep = (newEnvForm as typeof newEnvForm & { language?: string; entrypoint?: string }).entrypoint ?? "solution.py";
                const setLang = (v: string) => {
                    const defaultEp = LANG_OPTS.find(l => l.value === v)?.defaultEp ?? "solution.py";
                    const spec = { language: v, entrypoint: defaultEp };
                    setNewEnvForm(p => ({ ...p, language: v, entrypoint: defaultEp, specJson: JSON.stringify(spec, null, 2), specError: null } as typeof p));
                };
                const setEp = (v: string) => {
                    const spec = { language: lang, entrypoint: v };
                    setNewEnvForm(p => ({ ...p, entrypoint: v, specJson: JSON.stringify(spec, null, 2), specError: null } as typeof p));
                };
                return (
                    <div className="card" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
                        <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: "var(--space-4)" }}>Create New Environment Version</h4>
                        <div className="flex flex-col gap-4">
                            {/* Language picker */}
                            <div className="input-group">
                                <label className="input-label">Language *</label>
                                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                                    {LANG_OPTS.map(lo => (
                                        <button key={lo.value} type="button"
                                            onClick={() => setLang(lo.value)}
                                            style={{
                                                padding: "var(--space-1) var(--space-3)",
                                                borderRadius: "var(--radius)",
                                                fontSize: 12, fontWeight: 600, cursor: "pointer",
                                                border: `2px solid ${lang === lo.value ? "var(--accent)" : "var(--border)"}`,
                                                background: lang === lo.value ? "var(--accent-dim)" : "var(--bg-elevated)",
                                                color: lang === lo.value ? "var(--accent)" : "var(--text-muted)",
                                                transition: "all 0.15s",
                                            }}>
                                            {lo.label}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Entrypoint */}
                            <div className="input-group">
                                <label className="input-label">Entrypoint File *</label>
                                <input className="input" style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}
                                    value={ep} onChange={e => setEp(e.target.value)}
                                    placeholder="solution.py" />
                                <span className="input-hint">The filename students must submit (e.g. solution.py, Main.java).</span>
                            </div>

                            {/* Reuse mode */}
                            <div className="input-group">
                                <label className="input-label">Scope</label>
                                <select className="input" value={newEnvForm.reuseMode}
                                    onChange={e => setNewEnvForm(p => ({ ...p, reuseMode: e.target.value }))}>
                                    <option value="assignment_only">Assignment only</option>
                                    <option value="course_reuse_with_assignment_overrides">Course-wide (with per-assignment overrides)</option>
                                </select>
                            </div>

                            {/* Advanced: raw spec_json */}
                            <details>
                                <summary style={{ fontSize: 11, color: "var(--text-muted)", cursor: "pointer", userSelect: "none" }}>
                                    ▶ Advanced spec_json (Docker / microVM)
                                </summary>
                                <textarea
                                    className={`input ${newEnvForm.specError ? "input-error" : ""}`}
                                    rows={4}
                                    style={{ fontFamily: "var(--font-mono)", fontSize: 11, marginTop: "var(--space-2)" }}
                                    value={newEnvForm.specJson}
                                    onChange={e => {
                                        const v = e.target.value;
                                        let specError: string | null = null;
                                        try { JSON.parse(v); } catch { specError = "Invalid JSON"; }
                                        setNewEnvForm(p => ({ ...p, specJson: v, specError }));
                                    }}
                                />
                                {newEnvForm.specError && <span style={{ fontSize: 11, color: "var(--danger)" }}>{newEnvForm.specError}</span>}
                            </details>
                        </div>
                        <div className="flex items-center gap-3" style={{ marginTop: "var(--space-4)" }}>
                            <button className="btn btn-primary btn-sm" onClick={() => createMutation.mutate()}
                                disabled={createMutation.isPending || !!newEnvForm.specError || !ep.trim()}>
                                {createMutation.isPending ? <><RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} /> Creating…</> : <><Plus size={12} /> Create Environment</>}
                            </button>
                            <button className="btn btn-ghost btn-sm" onClick={() => setShowCreateForm(false)}>Cancel</button>
                        </div>
                    </div>
                );
            })()}


            {/* Env list */}
            {isLoading ? (
                <div className="flex flex-col gap-3">
                    {[...Array(2)].map((_, i) => <div key={i} className="skeleton" style={{ height: 80, borderRadius: "var(--radius-lg)" }} />)}
                </div>
            ) : displayVersions.length === 0 ? (
                <div className="empty-state">
                    <Code2 size={36} className="empty-icon" />
                    <div className="empty-title">No environments yet</div>
                    <div className="empty-message">Create an environment above to enable code evaluation for this assignment.</div>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {displayVersions.map(env => {
                        const isSelected = selectedId === env.id;
                        const spec = env.spec_json as { language?: string; entrypoint?: string; cpu_limit?: number; memory_limit_mb?: number; time_limit_seconds?: number } ?? {};
                        return (
                            <div key={env.id} style={{
                                border: `2px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                                borderRadius: "var(--radius-lg)",
                                background: isSelected ? "var(--accent-dim)" : "var(--card-bg)",
                                padding: "var(--space-4)",
                                cursor: "pointer",
                                transition: "all 0.15s",
                            }} onClick={() => {
                                const next = isSelected ? "" : env.id;
                                setSelectedId(next);
                                onEnvSelected(next || null);
                            }}>
                                <div className="flex items-center gap-3">
                                    <div style={{
                                        width: 36, height: 36, borderRadius: "var(--radius)",
                                        background: `${statusColor[env.status] ?? "var(--text-muted)"}22`,
                                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0
                                    }}>
                                        <Server size={16} style={{ color: statusColor[env.status] ?? "var(--text-muted)" }} />
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <div className="flex items-center gap-2">
                                            <span style={{ fontSize: 13, fontWeight: 600 }}>{env.profile_key || env.id.slice(0, 8)}</span>
                                            <span className={`badge ${statusClass[env.status] ?? "badge-default"}`} style={{ fontSize: 10 }}>{env.status}</span>
                                            {spec.language && <span className="badge badge-default" style={{ fontSize: 10 }}>{String(spec.language)}</span>}
                                            {isSelected && <span className="badge badge-accent" style={{ fontSize: 10 }}>✓ Selected</span>}
                                        </div>
                                        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                                            {spec.entrypoint && `${spec.entrypoint}`}
                                            {spec.cpu_limit !== undefined && ` · ${spec.cpu_limit} CPU`}
                                            {spec.memory_limit_mb !== undefined && ` · ${spec.memory_limit_mb}MB`}
                                            {spec.time_limit_seconds !== undefined && ` · ${spec.time_limit_seconds}s limit`}
                                            {` · v${env.version_number}`}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                                        {env.status !== "ready" && (
                                            <button className="btn btn-secondary btn-sm"
                                                onClick={() => buildMutation.mutate(env.id)}
                                                disabled={buildingId === env.id || env.status === "building"}>
                                                {buildingId === env.id || env.status === "building"
                                                    ? <><RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} /> Building…</>
                                                    : <><RefreshCw size={12} /> Build</>}
                                            </button>
                                        )}
                                    </div>
                                </div>
                                {env.status === "failed" && env.build_logs && (
                                    <details style={{ marginTop: "var(--space-3)" }}>
                                        <summary style={{ fontSize: 11, color: "var(--danger)", cursor: "pointer" }}>View build log</summary>
                                        <pre style={{ fontSize: 10, color: "var(--text-muted)", background: "var(--bg-elevated)", padding: "var(--space-3)", borderRadius: "var(--radius-sm)", maxHeight: 150, overflow: "auto", marginTop: "var(--space-2)", lineHeight: 1.4 }}>
                                            {env.build_logs}
                                        </pre>
                                    </details>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {selectedId && (
                <div style={{ padding: "var(--space-3)", background: "var(--success-dim)", borderRadius: "var(--radius)", border: "1px solid rgba(34,197,94,0.3)", fontSize: 12, color: "var(--success)", display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                    <CheckCircle size={14} /> Environment selected — use <strong>Publish</strong> on the Overview tab to deploy.
                </div>
            )}
        </div>
    );
}

// ── Test Cases Tab ─────────────────────────────────────────────────────────

function TestCasesTab({ assignment }: { assignment: Assignment }) {
    const { actor } = useAuth();
    const { toast } = useToast();
    const qc = useQueryClient();

    // Derive language/entrypoint from the assignment's linked environment if possible
    const [mode, setMode] = useState<"mode2" | "mode3">("mode3");
    const [qtext, setQtext] = useState(assignment.description || "");
    const [solution, setSolution] = useState("");
    const [language, setLanguage] = useState("python");
    const [entrypoint, setEntrypoint] = useState("solution.py");
    const [numCases, setNumCases] = useState(6);
    const [generating, setGenerating] = useState(false);
    const [showSolutionId, setShowSolutionId] = useState<string | null>(null);
    const [expandedRawId, setExpandedRawId] = useState<string | null>(null);

    // Load environment to auto-fill language/entrypoint
    const { data: envVersions = [] } = useQuery({
        queryKey: ["env-versions", assignment.id],
        queryFn: () => api.codeEval.environments.list({ assignment_id: assignment.id }),
    });
    React.useEffect(() => {
        const readyEnv = envVersions.find(e => e.status === "ready") ?? envVersions[0];
        if (readyEnv?.spec_json) {
            const spec = readyEnv.spec_json as { language?: string; entrypoint?: string };
            if (spec.language) setLanguage(spec.language);
            if (spec.entrypoint) setEntrypoint(spec.entrypoint);
        }
    }, [envVersions]);

    const { data: approvals = [], isLoading } = useQuery({
        queryKey: ["approvals", assignment.id],
        queryFn: () => api.codeEval.approvals.list(assignment.id),
    });

    const testApprovals = approvals.filter(a => a.artifact_type === "ai_tests");
    const pendingApproval = testApprovals.find(a => a.status === "pending");

    const generateMutation = useMutation({
        mutationFn: async () => {
            let approvalId = pendingApproval?.id;
            if (!approvalId) {
                const created = await api.codeEval.approvals.create({
                    assignment_id: assignment.id,
                    artifact_type: "ai_tests",
                    content_json: {},
                    status: "draft"
                });
                approvalId = created.id;
            }
            return api.codeEval.approvals.generateTests(approvalId, {
                question_text: qtext,
                solution_code: mode === "mode2" ? solution : undefined,
                language,
                entrypoint,
                num_cases: numCases,
                mode
            });
        },
        onSuccess: () => {
            toast("success", "Test cases generated!", "Review each case below — check stdin values carefully before approving.");
            qc.invalidateQueries({ queryKey: ["approvals", assignment.id] });
        },
        onError: (e: Error) => toast("error", "Generation failed", e.message),
        onSettled: () => setGenerating(false)
    });

    const approveMutation = useMutation({
        mutationFn: (id: string) => api.codeEval.approvals.approve(id, actor || "ta"),
        onSuccess: () => {
            toast("success", "Test cases approved", "They will be used for grading on next submission dispatch.");
            qc.invalidateQueries({ queryKey: ["approvals", assignment.id] });
        },
        onError: (e: Error) => toast("error", "Approval failed", e.message),
    });

    // Validate a set of testcases and return warning strings
    const validateTestcases = (tcs: Array<Record<string, unknown>>) => {
        const warnings: string[] = [];
        const allStdinNull = tcs.every(tc => !tc.stdin || String(tc.stdin).trim() === "");
        const outputs = new Set(tcs.map(tc => tc.expected_stdout));
        if (allStdinNull && tcs.length > 1 && outputs.size > 1) {
            warnings.push("⚠ All testcases have no stdin — the program won't know which function to call. Regenerate using a clearer problem statement.");
        }
        const emptyOutputCases = tcs.filter(tc => !tc.expected_stdout || String(tc.expected_stdout).trim() === "");
        if (emptyOutputCases.length > 0) {
            warnings.push(`⚠ ${emptyOutputCases.length} testcase(s) have empty expected_stdout — they would pass any output.`);
        }
        if (outputs.size === 1 && tcs.length > 1) {
            warnings.push("⚠ All testcases expect identical output — they may not be discriminating different inputs.");
        }
        return warnings;
    };

    if (isLoading) return <div className="skeleton" style={{ height: 300, borderRadius: "var(--radius-lg)" }} />;

    return (
        <div className="flex flex-col gap-6">
            {/* Generator */}
            <div className="card">
                <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: "var(--space-1)" }}>Generate AI Test Cases</h3>
                <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: "var(--space-5)" }}>
                    The AI uses your problem statement to generate stdin-driven testcases. Language &amp; entrypoint are pulled from the Environment tab automatically.
                </p>
                <div className="flex flex-col gap-4">
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                        <div className="input-group">
                            <label className="input-label">Generation Mode</label>
                            <select className="input" value={mode} onChange={e => setMode(e.target.value as "mode2" | "mode3")}>
                                <option value="mode3">Mode 3 — AI writes solution + tests</option>
                                <option value="mode2">Mode 2 — I provide the reference solution</option>
                            </select>
                            <span className="input-hint">{mode === "mode3" ? "AI generates and verifies test outputs. You review the solution before approving." : "Your solution is treated as ground truth for expected outputs."}</span>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-2)" }}>
                            <div className="input-group">
                                <label className="input-label">Language</label>
                                <input className="input" value={language} onChange={e => setLanguage(e.target.value)}
                                    style={{ fontFamily: "var(--font-mono)", fontSize: 12 }} />
                                <span className="input-hint">Auto-filled from Environment tab</span>
                            </div>
                            <div className="input-group">
                                <label className="input-label">Entrypoint</label>
                                <input className="input" value={entrypoint} onChange={e => setEntrypoint(e.target.value)}
                                    style={{ fontFamily: "var(--font-mono)", fontSize: 12 }} />
                            </div>
                        </div>
                    </div>

                    {mode === "mode2" && (
                        <div className="input-group">
                            <label className="input-label">Your Reference Solution *</label>
                            <textarea className="input" rows={7} value={solution} onChange={e => setSolution(e.target.value)}
                                style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
                                placeholder="Paste your working solution code here..." />
                            <span className="input-hint">Test expected outputs are computed by executing your solution.</span>
                        </div>
                    )}

                    <div className="input-group">
                        <label className="input-label">Problem Statement *</label>
                        <textarea className="input" rows={6} value={qtext} onChange={e => setQtext(e.target.value)}
                            placeholder={"Describe every function the student must implement.\nInclude: function name, signature, what it returns/prints, and sample I/O.\n\nExample:\n  1. swap_case(s: str) → prints the result\n  2. find_second_largest(nums: list) → prints the result"} />
                        <span className="input-hint">
                            For multi-function problems: list each function name, signature, and a sample call + output. The AI uses this to build stdin discriminators.
                        </span>
                    </div>

                    <div className="flex items-center gap-3">
                        <div className="input-group" style={{ maxWidth: 140, marginBottom: 0 }}>
                            <label className="input-label">Count</label>
                            <input type="number" className="input" min={2} max={20} value={numCases}
                                onChange={e => setNumCases(Number(e.target.value))} />
                        </div>
                        <button className="btn btn-primary" style={{ alignSelf: "flex-end" }}
                            onClick={() => { setGenerating(true); generateMutation.mutate(); }}
                            disabled={generating || generateMutation.isPending || !qtext.trim()}>
                            {generating || generateMutation.isPending
                                ? <><RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} /> Generating…</>
                                : <><Sparkles size={14} /> Generate Test Cases</>}
                        </button>
                    </div>
                </div>
            </div>

            {/* Approvals list */}
            {testApprovals.length > 0 && (
                <div className="card">
                    <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: "var(--space-4)" }}>
                        Generated Test Suites ({testApprovals.length})
                    </h3>
                    <div className="flex flex-col gap-5">
                        {testApprovals.map(approval => {
                            const tcs = ((approval.content_json as Record<string, unknown>)?.testcases ?? []) as Array<Record<string, unknown>>;
                            const genSolution = (approval.content_json as Record<string, unknown>)?.generated_solution as string | undefined;
                            const warnings = validateTestcases(tcs);
                            const hasWarnings = warnings.length > 0;
                            const isExpanded = expandedRawId === approval.id;
                            return (
                                <div key={approval.id} style={{
                                    border: `2px solid ${approval.status === "approved" ? "rgba(34,197,94,0.4)" : hasWarnings ? "rgba(245,158,11,0.4)" : "var(--border)"}`,
                                    borderRadius: "var(--radius-lg)", overflow: "hidden",
                                }}>
                                    {/* Header */}
                                    <div style={{ padding: "var(--space-3) var(--space-4)", background: approval.status === "approved" ? "var(--success-dim)" : "var(--bg-elevated)", display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                                        <div style={{ flex: 1 }}>
                                            <div className="flex items-center gap-2">
                                                <span style={{ fontSize: 12, fontWeight: 700 }}>{tcs.length} test cases</span>
                                                <span className={`badge ${approval.status === "approved" ? "badge-success" : approval.status === "pending" ? "badge-warning" : "badge-default"}`}>{approval.status}</span>
                                                {hasWarnings && <span className="badge badge-warning"><AlertTriangle size={9} style={{ display: "inline" }} /> {warnings.length} warning{warnings.length > 1 ? "s" : ""}</span>}
                                            </div>
                                            <div style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginTop: 2 }}>{approval.id}</div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {genSolution && (
                                                <button className="btn btn-ghost btn-sm"
                                                    onClick={() => setShowSolutionId(showSolutionId === approval.id ? null : approval.id)}>
                                                    <Eye size={12} /> {showSolutionId === approval.id ? "Hide" : "View"} Solution
                                                </button>
                                            )}
                                            <button className="btn btn-ghost btn-sm"
                                                onClick={() => setExpandedRawId(isExpanded ? null : approval.id)}>
                                                {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                                {isExpanded ? "Collapse" : "Raw JSON"}
                                            </button>
                                        </div>
                                    </div>

                                    {/* Warnings */}
                                    {hasWarnings && (
                                        <div style={{ padding: "var(--space-3) var(--space-4)", background: "var(--warning-dim)", borderBottom: "1px solid rgba(245,158,11,0.2)" }}>
                                            {warnings.map((w, i) => (
                                                <div key={i} style={{ fontSize: 12, color: "var(--warning)", lineHeight: 1.5 }}>{w}</div>
                                            ))}
                                        </div>
                                    )}

                                    {/* AI Solution preview */}
                                    {showSolutionId === approval.id && genSolution && (
                                        <div style={{ padding: "var(--space-3) var(--space-4)", borderBottom: "1px solid var(--border)", background: "var(--bg-surface)" }}>
                                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginBottom: "var(--space-2)" }}>AI-Generated Reference Solution</div>
                                            <pre style={{ fontSize: 11, color: "var(--text-primary)", background: "var(--bg-base)", padding: "var(--space-3)", borderRadius: "var(--radius-sm)", maxHeight: 280, overflow: "auto", lineHeight: 1.5 }}>
                                                {genSolution}
                                            </pre>
                                        </div>
                                    )}

                                    {/* Rendered testcase table */}
                                    {!isExpanded && tcs.length > 0 && (
                                        <div style={{ overflowX: "auto" }}>
                                            <table className="data-table" style={{ fontSize: 11 }}>
                                                <thead>
                                                    <tr>
                                                        <th style={{ width: 90 }}>ID</th>
                                                        <th style={{ width: 80 }}>Class</th>
                                                        <th>stdin</th>
                                                        <th>expected stdout</th>
                                                        <th style={{ width: 60 }}>Weight</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {tcs.map((tc, i) => {
                                                        const hasNoStdin = !tc.stdin || String(tc.stdin).trim() === "";
                                                        return (
                                                            <tr key={i} style={{ background: hasNoStdin ? "rgba(245,158,11,0.06)" : undefined }}>
                                                                <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>{String(tc.testcase_id ?? `tc_${i + 1}`)}</td>
                                                                <td>
                                                                    <span className={`badge ${tc.testcase_class === "happy_path" ? "badge-success" : tc.testcase_class === "edge_case" ? "badge-accent" : "badge-default"}`} style={{ fontSize: 9 }}>
                                                                        {String(tc.testcase_class ?? "—")}
                                                                    </span>
                                                                </td>
                                                                <td>
                                                                    {hasNoStdin
                                                                        ? <span style={{ color: "var(--warning)", fontStyle: "italic" }}>⚠ empty</span>
                                                                        : <code style={{ fontSize: 10, background: "var(--bg-elevated)", padding: "1px 4px", borderRadius: 3, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{String(tc.stdin)}</code>
                                                                    }
                                                                </td>
                                                                <td>
                                                                    <code style={{ fontSize: 10, background: "var(--bg-elevated)", padding: "1px 4px", borderRadius: 3, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                                                                        {tc.expected_stdout ? String(tc.expected_stdout) : <span style={{ color: "var(--danger)" }}>⚠ empty</span>}
                                                                    </code>
                                                                </td>
                                                                <td style={{ textAlign: "center" }}>{String(tc.weight ?? 1)}</td>
                                                            </tr>
                                                        );
                                                    })}
                                                </tbody>
                                            </table>
                                        </div>
                                    )}

                                    {/* Raw JSON */}
                                    {isExpanded && (
                                        <pre style={{ fontSize: 10, color: "var(--text-secondary)", background: "var(--bg-base)", padding: "var(--space-3)", maxHeight: 350, overflow: "auto", margin: "var(--space-3)" }}>
                                            {JSON.stringify(approval.content_json, null, 2)}
                                        </pre>
                                    )}

                                    {/* Approve action */}
                                    {approval.status === "pending" && (
                                        <div style={{ padding: "var(--space-3) var(--space-4)", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                                            {hasWarnings && (
                                                <span style={{ fontSize: 11, color: "var(--warning)" }}>
                                                    Review warnings above before approving.
                                                </span>
                                            )}
                                            <button className={`btn btn-sm ${hasWarnings ? "btn-secondary" : "btn-primary"}`}
                                                onClick={() => approveMutation.mutate(approval.id)}
                                                disabled={approveMutation.isPending}
                                                style={{ marginLeft: "auto" }}>
                                                <CheckCircle size={13} /> {hasWarnings ? "Approve Anyway" : "Approve Test Cases"}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}


// ── Main page ─────────────────────────────────────────────────────────────

const TABS_BASE = [
    { id: "overview", label: "Overview", icon: BookOpen, codingOnly: false },
    { id: "coding", label: "Environment", icon: Code2, codingOnly: true },
    { id: "test_cases", label: "Test Cases", icon: Sparkles, codingOnly: true },
    { id: "rubric", label: "Rubric & Questions", icon: ListChecks, codingOnly: false },
    { id: "submissions", label: "Submissions", icon: FileText, codingOnly: false },
    { id: "classroom", label: "Classroom", icon: Globe, codingOnly: false },
];

export default function AssignmentDetailPage() {
    const { id } = useParams<{ id: string }>();
    const router = useRouter();
    const qc = useQueryClient();
    const { actor } = useAuth();
    const { toast } = useToast();
    const [activeTab, setActiveTab] = useState("overview");
    const [publishConfirm, setPublishConfirm] = useState(false);
    const [selectedEnvId, setSelectedEnvId] = useState<string | null>(null);

    const { data: assignment, isLoading: aLoading } = useQuery({
        queryKey: ["assignment", id],
        queryFn: () => api.assignments.get(id),
    });
    const { data: rubric, refetch: refetchRubric } = useQuery({
        queryKey: ["rubric", id],
        queryFn: () => api.rubrics.getForAssignment(id),
        enabled: !!id,
    });
    // Live env versions — used for checklist and auto-selecting best env
    const { data: envVersions = [] } = useQuery<EnvironmentVersion[]>({
        queryKey: ["env-versions-page", id],
        queryFn: () => api.codeEval.environments.list({ assignment_id: id }),
        enabled: !!id && !!assignment?.has_code_question,
        refetchInterval: (q) => {
            const d = q.state.data as EnvironmentVersion[] | undefined;
            const hasBuilding = Array.isArray(d) && d.some((e: EnvironmentVersion) => e.status === "building");
            return hasBuilding ? 4000 : false;
        },
    });
    // Auto-select best env when versions load
    React.useEffect(() => {
        if (selectedEnvId) return; // already chosen
        const best = envVersions.find((e: EnvironmentVersion) => e.status === "ready") ??
            envVersions.find((e: EnvironmentVersion) => e.status === "building") ??
            envVersions[0];
        if (best) setSelectedEnvId(best.id);
    }, [envVersions]);

    // Live approvals — used for checklist test_cases check
    const { data: approvals = [] } = useQuery({
        queryKey: ["approvals-page", id],
        queryFn: () => api.codeEval.approvals.list(id),
        enabled: !!id && !!assignment?.has_code_question,
    });
    const hasApprovedTests = approvals.some(
        a => a.artifact_type === "ai_tests" && a.status === "approved"
    );

    const { data: validation, refetch: refetchValidation } = useQuery({
        queryKey: ["validation", id, selectedEnvId],
        queryFn: () => api.assignments.validatePublish(id, selectedEnvId ?? undefined),
        enabled: !!id,
    });


    const publishMutation = useMutation({
        mutationFn: () => api.assignments.publish(id, actor ?? "ta", selectedEnvId ?? undefined, assignment?.is_published),
        onSuccess: () => {
            toast("success", "Assignment published!", "Submissions can now be graded.");
            qc.invalidateQueries({ queryKey: ["assignment", id] });
            refetchValidation();
            setPublishConfirm(false);
        },
        onError: (e: Error) => { toast("error", "Publish failed", e.message); setPublishConfirm(false); },
    });
    const updatePromptMutation = useMutation({
        mutationFn: (nextPrompt: string) => api.assignments.update(id, { authoring_prompt: nextPrompt }),
        onSuccess: () => {
            toast("success", "Prompt updated", "Saved assignment authoring prompt.");
            qc.invalidateQueries({ queryKey: ["assignment", id] });
        },
        onError: (e: Error) => toast("error", "Failed to update prompt", e.message),
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
                    {TABS_BASE
                        .filter(t => !t.codingOnly || assignment.has_code_question)
                        .map(({ id: tid, label, icon: Icon }) => (
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
                        envVersions={envVersions}
                        hasApprovedTests={hasApprovedTests}
                        onUpdateAuthoringPrompt={async (nextPrompt: string) => {
                            await updatePromptMutation.mutateAsync(nextPrompt);
                        }}
                    />
                )}
                {activeTab === "submissions" && (
                    <SubmissionsTab assignmentId={id} maxMarks={assignment.max_marks} />
                )}
                {activeTab === "rubric" && (
                    <RubricTab
                        assignment={assignment}
                        onRefresh={() => { refetchRubric(); qc.invalidateQueries({ queryKey: ["rubrics-all", id] }); }}
                    />
                )}
                {activeTab === "coding" && assignment.has_code_question && (
                    <EnvironmentTab assignment={assignment} onEnvSelected={setSelectedEnvId} />
                )}
                {activeTab === "test_cases" && assignment.has_code_question && (
                    <TestCasesTab assignment={assignment} />
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
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
        </PageShell>
    );
}
