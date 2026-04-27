"use client";
import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
    ArrowLeft, FileText, Code2, Sparkles, ChevronRight, ChevronLeft,
    Calendar, Hash, BookOpen, PenLine, Edit3, Terminal, CheckCircle,
    AlertTriangle,
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { QuestionType } from "@/lib/types";

type AssignmentKind = "subjective" | "objective" | "coding";
type RubricMode = "ai" | "natural_language" | "manual" | "later";

const LANGUAGE_OPTIONS = [
    { value: "python", label: "Python", ext: "solution.py" },
    { value: "javascript", label: "JavaScript", ext: "solution.js" },
    { value: "java", label: "Java", ext: "Main.java" },
    { value: "cpp", label: "C++", ext: "solution.cpp" },
    { value: "c", label: "C", ext: "solution.c" },
];

const KIND_OPTIONS = [
    {
        value: "subjective" as AssignmentKind,
        label: "Subjective",
        desc: "Long-form answers graded by AI rubric with OCR",
        icon: <FileText size={20} style={{ color: "var(--text-secondary)" }} />,
    },
    {
        value: "objective" as AssignmentKind,
        label: "Objective",
        desc: "MCQ / short answer with structured answer key",
        icon: <Hash size={20} style={{ color: "var(--info)" }} />,
    },
    {
        value: "coding" as AssignmentKind,
        label: "Coding",
        desc: "Code submissions auto-evaluated with AI-generated test cases",
        icon: <Code2 size={20} style={{ color: "var(--accent)" }} />,
    },
];

function StepDots({ current, total, labels }: { current: number; total: number; labels: string[] }) {
    return (
        <div className="flex items-center gap-2" style={{ marginBottom: "var(--space-8)" }}>
            {Array.from({ length: total }, (_, i) => (
                <React.Fragment key={i}>
                    <div style={{
                        display: "flex", alignItems: "center", gap: 6,
                    }}>
                        <div style={{
                            width: i < current ? 28 : 28,
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
                        }}>
                            {i < current ? "✓" : i + 1}
                        </div>
                        <span style={{
                            fontSize: 11,
                            fontWeight: i === current ? 600 : 400,
                            color: i === current ? "var(--text-primary)" : "var(--text-muted)",
                            display: "none",
                        }} className="md-show">{labels[i]}</span>
                    </div>
                    {i < total - 1 && (
                        <div style={{
                            flex: 1, height: 2,
                            background: i < current ? "var(--success)" : "var(--border)",
                            borderRadius: 1,
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

    // Rubric config (subjective / objective)
    const [rubricMode, setRubricMode] = useState<RubricMode>("ai");
    const [assignmentContent, setAssignmentContent] = useState("");
    const [nlRubric, setNlRubric] = useState("");
    const [generatingRubric, setGeneratingRubric] = useState(false);

    // Coding-specific config
    const [problemStatement, setProblemStatement] = useState("");
    const [codingLanguage, setCodingLanguage] = useState("python");
    const [entrypoint, setEntrypoint] = useState("solution.py");
    const [customEntrypoint, setCustomEntrypoint] = useState(false);

    const STEPS = kind === "coding"
        ? ["Details", "Type", "Problem Setup", "Review"]
        : ["Details", "Type", "Rubric Setup", "Review"];

    const createMutation = useMutation({
        mutationFn: () => api.assignments.create({
            course_id: courseId ?? "default",
            title: title.trim(),
            // For coding: description IS the problem statement (used by AI test generator)
            description: kind === "coding"
                ? problemStatement.trim() || undefined
                : description.trim() || undefined,
            max_marks: parseFloat(maxMarks) || 100,
            question_type: (kind === "coding" ? "subjective" : kind) as QuestionType,
            has_code_question: kind === "coding",
            deadline: deadline ? new Date(deadline).toISOString() : undefined,
            classroom_id: classroomId.trim() || undefined,
        }),
        onSuccess: async (a) => {
            qc.invalidateQueries({ queryKey: ["assignments"] });

            if (kind === "coding") {
                // Auto-create the environment version with the chosen language + entrypoint
                try {
                    const ep = customEntrypoint ? entrypoint.trim() : LANGUAGE_OPTIONS.find(l => l.value === codingLanguage)?.ext ?? "solution.py";
                    await api.codeEval.environments.create({
                        course_id: courseId ?? "default",
                        assignment_id: a.id,
                        profile_key: `${codingLanguage}-latest`,
                        reuse_mode: "assignment_only",
                        spec_json: { language: codingLanguage, entrypoint: ep },
                        created_by: actor ?? "instructor",
                    });
                } catch {
                    // Non-fatal — user can set up environment from the assignment page
                }
                toast("success", "Assignment created!", `"${a.title}" is ready — go to the Test Cases tab to generate test cases, then publish.`);
            } else if (rubricMode !== "later" && (assignmentContent.trim() || nlRubric.trim())) {
                setGeneratingRubric(true);
                try {
                    if (rubricMode === "ai" && assignmentContent.trim()) {
                        await api.rubrics.generate(a.id, assignmentContent);
                        toast("success", "Assignment created!", `"${a.title}" created with AI-drafted rubric — approve it to start grading.`);
                    } else if (rubricMode === "natural_language" && nlRubric.trim()) {
                        await api.rubrics.encodeNaturalLanguage(a.id, nlRubric);
                        toast("success", "Assignment created!", `"${a.title}" created with rubric draft — approve it to start grading.`);
                    } else {
                        toast("success", "Assignment created!", `"${a.title}" is ready — add a rubric to start grading.`);
                    }
                } catch {
                    toast("warning", "Assignment created!", "Rubric generation failed — you can retry from the Rubric tab.");
                } finally {
                    setGeneratingRubric(false);
                }
            } else {
                toast("success", "Assignment created!", `"${a.title}" is ready.`);
            }
            router.push(`/assignments/${a.id}`);
        },
        onError: (e: Error) => toast("error", "Failed to create", e.message),
    });

    const canProceed0 = title.trim().length > 0;
    const canProceed2 = kind === "coding" ? problemStatement.trim().length > 0 : true;

    const next = () => { if (step < STEPS.length - 1) setStep(s => s + 1); };
    const back = () => { if (step > 0) setStep(s => s - 1); };
    const isCreating = createMutation.isPending || generatingRubric;

    const selectedLang = LANGUAGE_OPTIONS.find(l => l.value === codingLanguage);

    return (
        <PageShell>
            <div style={{ maxWidth: 700, margin: "0 auto" }}>
                <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-8)" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => router.back()}>
                        <ArrowLeft size={14} /> Back
                    </button>
                    <div>
                        <h1 className="page-title">Create Assignment</h1>
                        <p className="page-subtitle">Step {step + 1} of {STEPS.length} — {STEPS[step]}</p>
                    </div>
                </div>

                <StepDots current={step} total={STEPS.length} labels={STEPS} />

                <AnimatePresence mode="wait">
                    {/* Step 0 — Details */}
                    {step === 0 && (
                        <motion.div key="step0" className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}>
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-6)" }}>Assignment Details</h2>
                            <div className="flex flex-col gap-5">
                                <div className="input-group">
                                    <label className="input-label" htmlFor="a-title">Title *</label>
                                    <input id="a-title" className="input" autoFocus
                                        placeholder="e.g. Midterm Exam — Unit 3"
                                        value={title} onChange={e => setTitle(e.target.value)} />
                                </div>

                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
                                    <div className="input-group">
                                        <label className="input-label" htmlFor="a-marks">Max Marks *</label>
                                        <input id="a-marks" className="input" type="number" min="1"
                                            placeholder="100" value={maxMarks}
                                            onChange={e => setMaxMarks(e.target.value)} />
                                    </div>
                                    <div className="input-group">
                                        <label className="input-label" htmlFor="a-deadline">
                                            <Calendar size={12} style={{ display: "inline", marginRight: 4 }} />
                                            Deadline
                                        </label>
                                        <input id="a-deadline" className="input" type="datetime-local"
                                            value={deadline} onChange={e => setDeadline(e.target.value)} />
                                    </div>
                                </div>

                                <div className="input-group">
                                    <label className="input-label" htmlFor="a-classroom">Google Classroom Coursework ID</label>
                                    <input id="a-classroom" className="input"
                                        placeholder="Optional — paste from Classroom URL"
                                        value={classroomId} onChange={e => setClassId(e.target.value)} />
                                    <span className="input-hint">Link this assignment to a Classroom coursework for syncing grades.</span>
                                </div>
                            </div>
                        </motion.div>
                    )}

                    {/* Step 1 — Type */}
                    {step === 1 && (
                        <motion.div key="step1" className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}>
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-2)" }}>Assignment Type</h2>
                            <p className="text-sm" style={{ color: "var(--text-muted)", marginBottom: "var(--space-6)" }}>
                                Choose how student work will be submitted and graded.
                            </p>

                            <div className="flex flex-col gap-3">
                                {KIND_OPTIONS.map(opt => (
                                    <button key={opt.value} type="button" onClick={() => setKind(opt.value)}
                                        style={{
                                            display: "flex", alignItems: "center", gap: "var(--space-4)",
                                            padding: "var(--space-4) var(--space-5)", borderRadius: "var(--radius-lg)",
                                            border: `2px solid ${kind === opt.value ? "var(--accent)" : "var(--border)"}`,
                                            background: kind === opt.value ? "var(--accent-dim)" : "var(--bg-elevated)",
                                            cursor: "pointer", textAlign: "left", width: "100%", transition: "all 0.15s",
                                        }}>
                                        <div style={{
                                            width: 44, height: 44, borderRadius: "var(--radius)",
                                            background: kind === opt.value ? "var(--bg-overlay)" : "var(--bg-surface)",
                                            display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                                        }}>
                                            {opt.icon}
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <div className="font-semibold" style={{ color: "var(--text-primary)", fontSize: 14 }}>{opt.label}</div>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{opt.desc}</div>
                                        </div>
                                        {kind === opt.value && (
                                            <div style={{ width: 18, height: 18, borderRadius: "50%", background: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                                <span style={{ color: "#fff", fontSize: 11 }}>✓</span>
                                            </div>
                                        )}
                                    </button>
                                ))}
                            </div>
                        </motion.div>
                    )}

                    {/* Step 2 — Coding Problem Setup */}
                    {step === 2 && kind === "coding" && (
                        <motion.div key="step2-coding" className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}>
                            <div className="flex items-center gap-2" style={{ marginBottom: "var(--space-2)" }}>
                                <Terminal size={16} style={{ color: "var(--accent)" }} />
                                <h2 className="text-lg font-semibold">Coding Problem Setup</h2>
                            </div>
                            <p className="text-sm" style={{ color: "var(--text-muted)", marginBottom: "var(--space-6)" }}>
                                This information is used by the AI to generate test cases. Be specific about function names, signatures, and expected behavior.
                            </p>

                            {/* Language */}
                            <div className="input-group" style={{ marginBottom: "var(--space-4)" }}>
                                <label className="input-label">Programming Language</label>
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "var(--space-2)" }}>
                                    {LANGUAGE_OPTIONS.map(lang => (
                                        <button key={lang.value} type="button"
                                            onClick={() => {
                                                setCodingLanguage(lang.value);
                                                if (!customEntrypoint) setEntrypoint(lang.ext);
                                            }}
                                            style={{
                                                padding: "var(--space-2) var(--space-3)",
                                                borderRadius: "var(--radius)",
                                                border: `2px solid ${codingLanguage === lang.value ? "var(--accent)" : "var(--border)"}`,
                                                background: codingLanguage === lang.value ? "var(--accent-dim)" : "var(--bg-elevated)",
                                                fontSize: 12, fontWeight: 600,
                                                color: codingLanguage === lang.value ? "var(--accent)" : "var(--text-muted)",
                                                cursor: "pointer", transition: "all 0.15s",
                                            }}>
                                            {lang.label}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Entrypoint */}
                            <div className="input-group" style={{ marginBottom: "var(--space-5)" }}>
                                <label className="input-label">Entrypoint File</label>
                                <div className="flex items-center gap-2">
                                    <input className="input" style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}
                                        value={entrypoint}
                                        onChange={e => { setEntrypoint(e.target.value); setCustomEntrypoint(true); }}
                                        placeholder="solution.py" />
                                </div>
                                <span className="input-hint">
                                    The filename students must submit. Auto-set from language ({selectedLang?.ext}). Change only if needed.
                                </span>
                            </div>

                            {/* Problem Statement */}
                            <div className="input-group">
                                <label className="input-label">
                                    Problem Statement *
                                    <span style={{ fontWeight: 400, color: "var(--text-muted)", marginLeft: 6 }}>
                                        — used by AI to generate test cases
                                    </span>
                                </label>
                                <textarea className="input" rows={9}
                                    placeholder={`Describe each function the student must implement. Include:\n• Function name and signature\n• What it should return / print\n• Edge cases to handle\n\nExample:\n  Implement these 3 functions in ${selectedLang?.ext ?? "solution.py"}:\n\n  1. swap_case(s: str) → str\n     Swaps the case of every character in s.\n     print(swap_case("Python 3.10"))  # → pYTHON 3.10\n\n  2. find_second_largest(nums: list) → int | None\n     Returns the second largest unique element, or None if < 2 unique elements.\n     print(find_second_largest([10, 20, 4, 45, 99, 99]))  # → 45`}
                                    value={problemStatement}
                                    onChange={e => setProblemStatement(e.target.value)} />
                                <span className="input-hint">
                                    The more detail you provide (especially function names + sample I/O), the better the AI test cases will be.
                                </span>
                            </div>

                            {/* Info box */}
                            <div style={{
                                marginTop: "var(--space-4)", padding: "var(--space-3) var(--space-4)",
                                borderRadius: "var(--radius)", background: "var(--accent-dim)",
                                border: "1px solid rgba(59,130,246,0.2)", fontSize: 12, color: "var(--text-secondary)",
                                display: "flex", gap: "var(--space-3)", alignItems: "flex-start",
                            }}>
                                <Sparkles size={14} style={{ color: "var(--accent)", flexShrink: 0, marginTop: 1 }} />
                                <div>
                                    <strong>What happens next:</strong> After creation, go to the <strong>Test Cases</strong> tab to generate AI test cases from this problem statement. Then go to <strong>Environment</strong> to verify the setup, and finally <strong>Publish</strong>.
                                </div>
                            </div>
                        </motion.div>
                    )}

                    {/* Step 2 — Rubric Setup (non-coding) */}
                    {step === 2 && kind !== "coding" && (
                        <motion.div key="step2-rubric" className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}>
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-2)" }}>Assignment Content & Rubric</h2>
                            <p className="text-sm" style={{ color: "var(--text-muted)", marginBottom: "var(--space-6)" }}>
                                Help the AI understand the assignment to auto-generate a rubric. You can also do this later from the Rubric tab.
                            </p>

                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)", marginBottom: "var(--space-5)" }}>
                                {([
                                    { value: "ai" as const, label: "AI from Assignment", desc: "Paste the question paper — AI infers questions & marks", icon: Sparkles },
                                    { value: "natural_language" as const, label: "Natural Language Rubric", desc: "Describe marks in plain English, AI encodes it", icon: PenLine },
                                    { value: "manual" as const, label: "Skip for now", desc: "Add rubric manually from the assignment workspace", icon: Edit3 },
                                    { value: "later" as const, label: "Set up later", desc: "Create the assignment now, configure rubric later", icon: BookOpen },
                                ] as const).map(opt => (
                                    <button key={opt.value} type="button" onClick={() => setRubricMode(opt.value)}
                                        style={{
                                            display: "flex", alignItems: "flex-start", gap: "var(--space-3)",
                                            padding: "var(--space-3) var(--space-4)", borderRadius: "var(--radius-lg)",
                                            border: `2px solid ${rubricMode === opt.value ? "var(--accent)" : "var(--border)"}`,
                                            background: rubricMode === opt.value ? "var(--accent-dim)" : "var(--bg-elevated)",
                                            cursor: "pointer", textAlign: "left", width: "100%", transition: "all 0.15s",
                                        }}>
                                        <opt.icon size={16} style={{ color: rubricMode === opt.value ? "var(--accent)" : "var(--text-muted)", marginTop: 2, flexShrink: 0 }} />
                                        <div>
                                            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{opt.label}</div>
                                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, lineHeight: 1.4 }}>{opt.desc}</div>
                                        </div>
                                    </button>
                                ))}
                            </div>

                            {rubricMode === "ai" && (
                                <div className="input-group">
                                    <label className="input-label">Question Paper / Assignment Description</label>
                                    <textarea className="input" rows={8}
                                        placeholder={`Paste the full question paper or describe the assignment.\nThe AI will infer how many questions exist and build a marking scheme for each.\n\nExample:\n  Q1. Explain the concept of recursion with an example. (10 marks)\n  Q2. Write pseudocode for merge sort and explain its time complexity. (15 marks)`}
                                        value={assignmentContent}
                                        onChange={e => setAssignmentContent(e.target.value)} />
                                    <span className="input-hint">
                                        Works for single or multiple questions. The AI will auto-allocate marks to sum to {maxMarks}.
                                    </span>
                                </div>
                            )}

                            {rubricMode === "natural_language" && (
                                <div className="input-group">
                                    <label className="input-label">Describe Your Rubric in Plain English</label>
                                    <textarea className="input" rows={6}
                                        placeholder={`e.g. "Q1 gets 15 marks — 5 for correct implementation, 5 for handling edge cases, 5 for code style.\nQ2 gets 10 marks — 7 for correct output, 3 for efficiency."`}
                                        value={nlRubric}
                                        onChange={e => setNlRubric(e.target.value)} />
                                </div>
                            )}

                            {(rubricMode === "manual" || rubricMode === "later") && (
                                <div style={{
                                    padding: "var(--space-4)", borderRadius: "var(--radius)",
                                    background: "var(--bg-elevated)", border: "1px solid var(--border)",
                                    fontSize: 13, color: "var(--text-muted)",
                                }}>
                                    <BookOpen size={14} style={{ display: "inline", marginRight: 6 }} />
                                    After creation, go to the <strong>Rubric & Questions</strong> tab to set up your marking scheme.
                                </div>
                            )}
                        </motion.div>
                    )}

                    {/* Step 3 — Review */}
                    {step === 3 && (
                        <motion.div key="step3" className="card"
                            initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
                            transition={{ duration: 0.2 }}>
                            <h2 className="text-lg font-semibold" style={{ marginBottom: "var(--space-6)" }}>Review & Create</h2>
                            <div className="flex flex-col gap-3">
                                {[
                                    { label: "Title", value: title || "—" },
                                    { label: "Type", value: KIND_OPTIONS.find(k => k.value === kind)?.label ?? kind },
                                    { label: "Max Marks", value: maxMarks },
                                    { label: "Course ID", value: courseId ?? "—" },
                                    { label: "Deadline", value: deadline ? new Date(deadline).toLocaleString() : "None" },
                                    ...(kind === "coding" ? [
                                        { label: "Language", value: LANGUAGE_OPTIONS.find(l => l.value === codingLanguage)?.label ?? codingLanguage },
                                        { label: "Entrypoint", value: entrypoint },
                                    ] : [
                                        { label: "Rubric Setup", value: rubricMode === "ai" ? "AI will generate from assignment text" : rubricMode === "natural_language" ? "AI will encode natural-language rubric" : "Set up manually later" },
                                    ]),
                                ].map(({ label, value }) => (
                                    <div key={label} style={{
                                        display: "flex", gap: "var(--space-4)",
                                        padding: "var(--space-3) 0",
                                        borderBottom: "1px solid var(--border)",
                                    }}>
                                        <div style={{ width: 140, flexShrink: 0, fontSize: 12, color: "var(--text-muted)", fontWeight: 500 }}>{label}</div>
                                        <div style={{ fontSize: 13, color: "var(--text-primary)", wordBreak: "break-all", fontFamily: label === "Entrypoint" ? "var(--font-mono)" : undefined }}>{value}</div>
                                    </div>
                                ))}
                            </div>

                            {kind === "coding" && (
                                <div style={{
                                    marginTop: "var(--space-5)", padding: "var(--space-4)",
                                    borderRadius: "var(--radius-lg)", background: "var(--accent-dim)",
                                    border: "1px solid rgba(59,130,246,0.2)",
                                }}>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: "var(--space-3)", display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                                        <Sparkles size={14} style={{ color: "var(--accent)" }} />
                                        After creation — your checklist:
                                    </div>
                                    {[
                                        "Go to Test Cases tab → Generate AI test cases from your problem statement",
                                        "Review the generated test cases and their stdin / expected output values",
                                        "Approve the test cases when they look correct",
                                        "Verify the Environment tab has the right language & entrypoint",
                                        "Publish the assignment",
                                    ].map((step, i) => (
                                        <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: "var(--space-3)", marginBottom: i < 4 ? "var(--space-2)" : 0 }}>
                                            <div style={{ width: 18, height: 18, borderRadius: "50%", background: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700, color: "#fff", flexShrink: 0, marginTop: 1 }}>{i + 1}</div>
                                            <span style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>{step}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Navigation */}
                <div className="flex justify-between items-center" style={{ marginTop: "var(--space-6)" }}>
                    <button className="btn btn-secondary" onClick={back} disabled={step === 0}>
                        <ChevronLeft size={14} /> Back
                    </button>

                    {step < STEPS.length - 1 ? (
                        <button className="btn btn-primary" onClick={next}
                            disabled={(step === 0 && !canProceed0) || (step === 2 && !canProceed2)}>
                            Continue <ChevronRight size={14} />
                        </button>
                    ) : (
                        <button className="btn btn-primary btn-lg"
                            onClick={() => createMutation.mutate()}
                            disabled={isCreating}>
                            {isCreating
                                ? generatingRubric ? "Generating rubric…" : "Creating…"
                                : "Create Assignment"}
                        </button>
                    )}
                </div>
            </div>
        </PageShell>
    );
}
