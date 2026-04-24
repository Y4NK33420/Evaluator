"use client";
import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeft, FileText, Code2, Sparkles, ChevronRight, ChevronLeft,
    Calendar, Hash, BookOpen,
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { QuestionType } from "@/lib/types";

type AssignmentKind = "subjective" | "objective" | "coding";

const KIND_OPTIONS: { value: AssignmentKind; label: string; desc: string; icon: React.ReactNode }[] = [
    {
        value: "subjective",
        label: "Subjective",
        desc: "Long-form answers graded by AI rubric with OCR",
        icon: <FileText size={20} style={{ color: "var(--text-secondary)" }} />,
    },
    {
        value: "objective",
        label: "Objective",
        desc: "MCQ / short answer with structured answer key",
        icon: <Hash size={20} style={{ color: "var(--info)" }} />,
    },
    {
        value: "coding",
        label: "Coding",
        desc: "Code submissions evaluated with test cases",
        icon: <Code2 size={20} style={{ color: "var(--accent)" }} />,
    },
];

function StepDots({ current, total }: { current: number; total: number }) {
    return (
        <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-8)" }}>
            {Array.from({ length: total }, (_, i) => (
                <React.Fragment key={i}>
                    <div style={{
                        width: i < current ? "auto" : 28,
                        height: 28,
                        minWidth: 28,
                        borderRadius: "var(--radius-full)",
                        background: i < current
                            ? "var(--success-dim)"
                            : i === current
                                ? "var(--accent)"
                                : "var(--bg-elevated)",
                        border: `2px solid ${i < current ? "rgba(34,197,94,0.4)" : i === current ? "var(--accent)" : "var(--border-medium)"}`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 12, fontWeight: 600, color: i <= current ? "#fff" : "var(--text-muted)",
                        transition: "all 0.2s",
                        padding: i < current ? "0 10px" : undefined,
                    }}>
                        {i < current ? "✓" : i + 1}
                    </div>
                    {i < total - 1 && (
                        <div style={{
                            flex: 1, height: 1,
                            background: i < current ? "var(--success)" : "var(--border)",
                            transition: "background 0.3s",
                        }} />
                    )}
                </React.Fragment>
            ))}
        </div>
    );
}

export default function NewAssignmentPage() {
    const { courseId, actor } = useAuth();
    const router = useRouter();
    const qc = useQueryClient();
    const { toast } = useToast();

    const [step, setStep] = useState(0);
    const [kind, setKind] = useState<AssignmentKind>("subjective");
    const [title, setTitle] = useState("");
    const [description, setDesc] = useState("");
    const [maxMarks, setMaxMarks] = useState("100");
    const [deadline, setDeadline] = useState("");
    const [classroomId, setClassId] = useState("");

    const STEPS = ["Details", "Configuration", "Review"];

    const createMutation = useMutation({
        mutationFn: () => api.assignments.create({
            course_id: courseId ?? "default",
            title: title.trim(),
            description: description.trim() || undefined,
            max_marks: parseFloat(maxMarks) || 100,
            question_type: (kind === "coding" ? "subjective" : kind) as QuestionType,
            has_code_question: kind === "coding",
            deadline: deadline ? new Date(deadline).toISOString() : undefined,
            classroom_id: classroomId.trim() || undefined,
        }),
        onSuccess: (a) => {
            qc.invalidateQueries({ queryKey: ["assignments"] });
            toast("success", "Assignment created!", `"${a.title}" is ready — add a rubric to start grading.`);
            router.push(`/assignments/${a.id}`);
        },
        onError: (e: Error) => toast("error", "Failed to create", e.message),
    });

    const canProceed0 = title.trim().length > 0;
    const canProceed1 = parseFloat(maxMarks) > 0;

    const next = () => { if (step < STEPS.length - 1) setStep(s => s + 1); };
    const back = () => { if (step > 0) setStep(s => s - 1); };

    return (
        <PageShell>
            <div style={{ maxWidth: 680, margin: "0 auto" }}>
                <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-8)" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => router.back()}>
                        <ArrowLeft size={14} /> Back
                    </button>
                    <div>
                        <h1 className="page-title">Create Assignment</h1>
                        <p className="page-subtitle">Step {step + 1} of {STEPS.length} — {STEPS[step]}</p>
                    </div>
                </div>

                <StepDots current={step} total={STEPS.length} />

                <AnimatePresence mode="wait">
                    {step === 0 && (
                        <motion.div key="step0"
                            className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}
                        >
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-6)" }}>
                                Assignment Details
                            </h2>

                            <div className="flex flex-col gap-5">
                                <div className="input-group">
                                    <label className="input-label" htmlFor="a-title">Title *</label>
                                    <input
                                        id="a-title" className="input" autoFocus
                                        placeholder="e.g. Midterm Exam — Unit 3"
                                        value={title}
                                        onChange={e => setTitle(e.target.value)}
                                    />
                                </div>

                                <div className="input-group">
                                    <label className="input-label" htmlFor="a-desc">Description / Instructions</label>
                                    <textarea
                                        id="a-desc" className="input"
                                        rows={3}
                                        placeholder="Optional notes visible to graders…"
                                        value={description}
                                        onChange={e => setDesc(e.target.value)}
                                    />
                                </div>

                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
                                    <div className="input-group">
                                        <label className="input-label" htmlFor="a-marks">Max Marks *</label>
                                        <input
                                            id="a-marks" className="input" type="number" min="1"
                                            placeholder="100"
                                            value={maxMarks}
                                            onChange={e => setMaxMarks(e.target.value)}
                                        />
                                    </div>
                                    <div className="input-group">
                                        <label className="input-label" htmlFor="a-deadline">
                                            <Calendar size={12} style={{ display: "inline", marginRight: 4 }} />
                                            Deadline
                                        </label>
                                        <input
                                            id="a-deadline" className="input" type="datetime-local"
                                            value={deadline}
                                            onChange={e => setDeadline(e.target.value)}
                                        />
                                    </div>
                                </div>

                                <div className="input-group">
                                    <label className="input-label" htmlFor="a-classroom">Google Classroom Coursework ID</label>
                                    <input
                                        id="a-classroom" className="input"
                                        placeholder="Optional — paste from Classroom URL"
                                        value={classroomId}
                                        onChange={e => setClassId(e.target.value)}
                                    />
                                    <span className="input-hint">Link this assignment to a Classroom coursework for syncing grades.</span>
                                </div>
                            </div>
                        </motion.div>
                    )}

                    {step === 1 && (
                        <motion.div key="step1"
                            className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}
                        >
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-2)" }}>
                                Assignment Type
                            </h2>
                            <p className="text-sm" style={{ color: "var(--text-muted)", marginBottom: "var(--space-6)" }}>
                                Choose how student work will be submitted and graded.
                            </p>

                            <div className="flex flex-col gap-3">
                                {KIND_OPTIONS.map(opt => (
                                    <button
                                        key={opt.value}
                                        type="button"
                                        onClick={() => setKind(opt.value)}
                                        style={{
                                            display: "flex", alignItems: "center", gap: "var(--space-4)",
                                            padding: "var(--space-4) var(--space-5)",
                                            borderRadius: "var(--radius-lg)",
                                            border: `2px solid ${kind === opt.value ? "var(--accent)" : "var(--border)"}`,
                                            background: kind === opt.value ? "var(--accent-dim)" : "var(--bg-elevated)",
                                            cursor: "pointer", textAlign: "left", width: "100%",
                                            transition: "all 0.15s",
                                        }}
                                    >
                                        <div style={{
                                            width: 44, height: 44,
                                            borderRadius: "var(--radius)",
                                            background: kind === opt.value ? "var(--bg-overlay)" : "var(--bg-surface)",
                                            display: "flex", alignItems: "center", justifyContent: "center",
                                            flexShrink: 0,
                                        }}>
                                            {opt.icon}
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <div className="font-semibold" style={{ color: "var(--text-primary)", fontSize: 14 }}>
                                                {opt.label}
                                            </div>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                                                {opt.desc}
                                            </div>
                                        </div>
                                        {kind === opt.value && (
                                            <div style={{
                                                width: 18, height: 18, borderRadius: "50%",
                                                background: "var(--accent)",
                                                display: "flex", alignItems: "center", justifyContent: "center",
                                                flexShrink: 0,
                                            }}>
                                                <span style={{ color: "#fff", fontSize: 11 }}>✓</span>
                                            </div>
                                        )}
                                    </button>
                                ))}
                            </div>

                            {kind === "coding" && (
                                <div style={{
                                    marginTop: "var(--space-4)",
                                    padding: "var(--space-3) var(--space-4)",
                                    borderRadius: "var(--radius)",
                                    background: "var(--accent-dim)",
                                    border: "1px solid rgba(59,130,246,0.2)",
                                    fontSize: 12,
                                    color: "var(--text-secondary)",
                                    display: "flex", alignItems: "flex-start", gap: "var(--space-2)",
                                }}>
                                    <Sparkles size={14} style={{ color: "var(--accent)", marginTop: 1, flexShrink: 0 }} />
                                    After creation, you'll set up the code evaluation environment, test cases, and rubric from the assignment workspace.
                                </div>
                            )}
                        </motion.div>
                    )}

                    {step === 2 && (
                        <motion.div key="step2"
                            className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}
                        >
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-6)" }}>
                                Review & Create
                            </h2>

                            <div className="flex flex-col gap-3">
                                {[
                                    { label: "Title", value: title || "—" },
                                    { label: "Type", value: KIND_OPTIONS.find(k => k.value === kind)?.label ?? kind },
                                    { label: "Max Marks", value: maxMarks },
                                    { label: "Course ID", value: courseId ?? "—" },
                                    { label: "Deadline", value: deadline ? new Date(deadline).toLocaleString() : "None" },
                                    { label: "Classroom ID", value: classroomId || "Not linked" },
                                    { label: "Description", value: description || "None" },
                                ].map(({ label, value }) => (
                                    <div key={label} style={{
                                        display: "flex", gap: "var(--space-4)",
                                        padding: "var(--space-3) 0",
                                        borderBottom: "1px solid var(--border)",
                                    }}>
                                        <div style={{ width: 120, flexShrink: 0, fontSize: 12, color: "var(--text-muted)", fontWeight: 500 }}>
                                            {label}
                                        </div>
                                        <div style={{ fontSize: 13, color: "var(--text-primary)", wordBreak: "break-all" }}>{value}</div>
                                    </div>
                                ))}
                            </div>

                            <div style={{
                                marginTop: "var(--space-6)",
                                padding: "var(--space-3) var(--space-4)",
                                borderRadius: "var(--radius)",
                                background: "var(--bg-elevated)",
                                border: "1px solid var(--border)",
                                fontSize: 12, color: "var(--text-muted)",
                            }}>
                                <BookOpen size={13} style={{ display: "inline", marginRight: 6 }} />
                                After creation, you'll be taken to the assignment workspace to add a rubric and upload submissions.
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Navigation */}
                <div className="flex justify-between items-center" style={{ marginTop: "var(--space-6)" }}>
                    <button className="btn btn-secondary" onClick={back} disabled={step === 0}>
                        <ChevronLeft size={14} /> Back
                    </button>

                    {step < STEPS.length - 1 ? (
                        <button
                            className="btn btn-primary"
                            onClick={next}
                            disabled={(step === 0 && !canProceed0) || (step === 1 && !canProceed1)}
                        >
                            Continue <ChevronRight size={14} />
                        </button>
                    ) : (
                        <button
                            className="btn btn-primary btn-lg"
                            onClick={() => createMutation.mutate()}
                            disabled={createMutation.isPending}
                        >
                            {createMutation.isPending ? "Creating…" : "Create Assignment"}
                        </button>
                    )}
                </div>
            </div>
        </PageShell>
    );
}
