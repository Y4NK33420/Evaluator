import { api } from "@/lib/api";
import Link from "next/link";
import { StatusBadge } from "@/components/StatusBadge";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "AMGS — Assignments" };
export const revalidate = 30;

export default async function HomePage() {
  let assignments: Awaited<ReturnType<typeof api.assignments.list>> = [];
  try { assignments = await api.assignments.list(); } catch { /* backend offline */ }

  return (
    <div className="animate-fade-in space-y-8">
      {/* Hero */}
      <div className="relative rounded-2xl overflow-hidden bg-gradient-to-br from-surface-2 to-surface-1 border border-white/[0.06] p-8">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_rgba(99,102,241,0.15),_transparent_70%)]" />
        <div className="relative">
          <h1 className="text-3xl font-bold gradient-text mb-2">Automated Grading</h1>
          <p className="text-slate-400 text-sm max-w-lg">
            Upload student exam scans → OCR → AI grading → TA review → Google Classroom sync.
            Objective questions use GLM-OCR (local GPU). Subjective questions use Gemini Vision.
          </p>
          <div className="flex gap-3 mt-5">
            <Link href="/assignments/new" className="px-4 py-2 rounded-xl bg-accent text-white text-sm font-semibold hover:bg-accent-dark transition-all shadow-md shadow-accent/25">
              + New Assignment
            </Link>
          </div>
        </div>
      </div>

      {/* Stats row */}
      {assignments.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Assignments",  value: assignments.length },
            { label: "Courses",      value: new Set(assignments.map(a => a.course_id)).size },
            { label: "Objective",    value: assignments.filter(a => a.question_type === "objective").length },
            { label: "Subjective",   value: assignments.filter(a => a.question_type === "subjective").length },
          ].map(s => (
            <div key={s.label} className="glass p-4">
              <p className="text-2xl font-bold text-slate-100">{s.value}</p>
              <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Assignment list */}
      <section>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest mb-3">All Assignments</h2>
        {assignments.length === 0 ? (
          <div className="glass p-12 text-center text-slate-500 text-sm">
            No assignments yet. Create one to get started.
          </div>
        ) : (
          <div className="grid gap-3">
            {assignments.map((a, i) => (
              <Link
                key={a.id}
                href={`/assignments/${a.id}`}
                className="glass card-hover p-4 flex items-center gap-4 group"
                style={{ animationDelay: `${i * 40}ms` }}
              >
                {/* Type indicator */}
                <div className={`h-10 w-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0 ${
                  a.question_type === "objective"  ? "bg-emerald-900/50 text-emerald-400" :
                  a.question_type === "subjective" ? "bg-violet-900/50 text-violet-400"  :
                                                     "bg-sky-900/50 text-sky-400"
                }`}>
                  {a.question_type === "objective" ? "○" : a.question_type === "subjective" ? "✍" : "⊕"}
                </div>

                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-100 truncate group-hover:text-accent-light transition-colors">
                    {a.title}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {a.course_id} · {a.max_marks} marks
                    {a.deadline && ` · Due ${new Date(a.deadline).toLocaleDateString()}`}
                  </p>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="pill bg-surface-3 text-slate-400 capitalize text-[10px]">
                    {a.question_type}
                  </span>
                  {a.has_code_question && (
                    <span className="pill bg-sky-900/50 text-sky-400 text-[10px]">code</span>
                  )}
                  <span className="text-slate-600 group-hover:text-slate-400 transition-colors text-sm">→</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
