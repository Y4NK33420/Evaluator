"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { api, type QuestionType } from "@/lib/api";
import Link from "next/link";

const QUESTION_TYPES: { value: QuestionType; label: string; desc: string; icon: string }[] = [
  { value: "objective",  label: "Objective",  icon: "○", desc: "MCQ / fill-in → GLM-OCR (bboxes + confidence)" },
  { value: "subjective", label: "Subjective", icon: "✍", desc: "Handwritten answers → Gemini Vision" },
  { value: "mixed",      label: "Mixed",      icon: "⊕", desc: "Both on the same paper — both engines run" },
];

export default function NewAssignmentPage() {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error,  setError]  = useState("");

  const [form, setForm] = useState({
    course_id:         "",
    classroom_id:      "",
    title:             "",
    description:       "",
    deadline:          "",
    max_marks:         "100",
    question_type:     "subjective" as QuestionType,
    has_code_question: false,
  });

  function set(k: string, v: unknown) { setForm(f => ({ ...f, [k]: v })); }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const payload = {
        ...form,
        max_marks: parseFloat(form.max_marks),
        deadline:  form.deadline || undefined,
        classroom_id: form.classroom_id || undefined,
      };
      const a = await api.assignments.create(payload);
      router.push(`/assignments/${a.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create assignment");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="animate-fade-in max-w-2xl mx-auto space-y-6">
      <nav className="text-xs text-slate-500 flex items-center gap-1.5">
        <Link href="/" className="hover:text-slate-300 transition-colors">Assignments</Link>
        <span>›</span>
        <span className="text-slate-300">New</span>
      </nav>

      <div className="glass p-6">
        <h1 className="text-xl font-bold gradient-text mb-6">New Assignment</h1>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Basic info */}
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block">
              <span className="text-xs font-medium text-slate-400 mb-1.5 block">Assignment Title *</span>
              <input required value={form.title} onChange={e => set("title", e.target.value)}
                className="w-full bg-surface-2 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-accent transition-colors"
                placeholder="e.g. Mid-Term Exam 2026" />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-400 mb-1.5 block">Course ID *</span>
              <input required value={form.course_id} onChange={e => set("course_id", e.target.value)}
                className="w-full bg-surface-2 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-accent transition-colors"
                placeholder="e.g. CS301" />
            </label>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block">
              <span className="text-xs font-medium text-slate-400 mb-1.5 block">Max Marks</span>
              <input type="number" min="1" value={form.max_marks} onChange={e => set("max_marks", e.target.value)}
                className="w-full bg-surface-2 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-accent transition-colors" />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-400 mb-1.5 block">Deadline</span>
              <input type="datetime-local" value={form.deadline} onChange={e => set("deadline", e.target.value)}
                className="w-full bg-surface-2 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-slate-400 focus:outline-none focus:border-accent transition-colors" />
            </label>
          </div>

          <label className="block">
            <span className="text-xs font-medium text-slate-400 mb-1.5 block">Description</span>
            <textarea rows={2} value={form.description} onChange={e => set("description", e.target.value)}
              className="w-full bg-surface-2 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-accent transition-colors resize-none"
              placeholder="Optional description for TAs" />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-slate-400 mb-1.5 block">Google Classroom Coursework ID <span className="text-slate-600">(optional)</span></span>
            <input value={form.classroom_id} onChange={e => set("classroom_id", e.target.value)}
              className="w-full bg-surface-2 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-slate-400 focus:outline-none focus:border-accent transition-colors"
              placeholder="Paste coursework ID from Classroom URL" />
          </label>

          {/* Question type */}
          <div>
            <span className="text-xs font-medium text-slate-400 mb-2 block">Question Type (sets OCR engine)</span>
            <div className="grid sm:grid-cols-3 gap-2">
              {QUESTION_TYPES.map(qt => (
                <motion.button
                  key={qt.value}
                  type="button"
                  whileTap={{ scale: 0.97 }}
                  onClick={() => set("question_type", qt.value)}
                  className={`p-3 rounded-xl border text-left transition-all ${
                    form.question_type === qt.value
                      ? "border-accent bg-accent/10 text-slate-100"
                      : "border-white/[0.08] bg-surface-2/60 text-slate-400 hover:border-white/20"
                  }`}
                >
                  <div className="text-xl mb-1">{qt.icon}</div>
                  <div className="text-sm font-medium">{qt.label}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{qt.desc}</div>
                </motion.button>
              ))}
            </div>
          </div>

          {/* Code question toggle */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <div
              onClick={() => set("has_code_question", !form.has_code_question)}
              className={`h-5 w-9 rounded-full transition-colors relative ${form.has_code_question ? "bg-accent" : "bg-surface-3"}`}
            >
              <div className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${form.has_code_question ? "left-[18px]" : "left-0.5"}`} />
            </div>
            <span className="text-sm text-slate-400 group-hover:text-slate-200 transition-colors">
              Has code question (enables Firecracker sandbox)
            </span>
          </label>

          {error && (
            <p className="text-xs text-danger bg-red-900/30 border border-red-800/40 rounded-xl px-3 py-2">{error}</p>
          )}

          <div className="flex gap-3 pt-1">
            <Link href="/" className="flex-1 py-2.5 rounded-xl text-sm font-medium text-slate-400 bg-surface-2 hover:bg-surface-3 transition-colors text-center">
              Cancel
            </Link>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-accent to-indigo-500 hover:opacity-90 disabled:opacity-50 transition-all shadow-md shadow-accent/20"
            >
              {saving ? "Creating…" : "Create Assignment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
