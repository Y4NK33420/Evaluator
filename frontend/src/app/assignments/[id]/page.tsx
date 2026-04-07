import { api } from "@/lib/api";
import Link from "next/link";
import { notFound } from "next/navigation";
import { StatusBadge } from "@/components/StatusBadge";
import type { Metadata } from "next";

interface Props { params: Promise<{ id: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  try {
    const a = await api.assignments.get(id);
    return { title: `AMGS — ${a.title}` };
  } catch { return { title: "Assignment" }; }
}

export const revalidate = 15;

export default async function AssignmentPage({ params }: Props) {
  const { id } = await params;

  let assignment: Awaited<ReturnType<typeof api.assignments.get>>;
  try { assignment = await api.assignments.get(id); }
  catch { notFound(); }

  const submissions = await api.submissions.list(id).catch(() => []);
  const rubrics     = await api.rubrics.list(id).catch(() => []);

  const statusCounts = submissions.reduce((acc, s) => {
    acc[s.status] = (acc[s.status] ?? 0) + 1; return acc;
  }, {} as Record<string, number>);

  const approvedRubric = rubrics.find(r => r.approved);

  return (
    <div className="animate-fade-in space-y-6">
      {/* Breadcrumb */}
      <nav className="text-xs text-slate-500 flex items-center gap-1.5">
        <Link href="/" className="hover:text-slate-300 transition-colors">Assignments</Link>
        <span>›</span>
        <span className="text-slate-300">{assignment.title}</span>
      </nav>

      {/* Header */}
      <div className="glass p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-slate-100">{assignment.title}</h1>
            {assignment.description && <p className="text-sm text-slate-400 mt-1">{assignment.description}</p>}
            <div className="flex flex-wrap gap-2 mt-3 text-xs">
              <span className="pill bg-surface-3 text-slate-300">Course: {assignment.course_id}</span>
              <span className="pill bg-surface-3 text-slate-300">{assignment.max_marks} marks</span>
              <span className="pill bg-surface-3 text-slate-300 capitalize">{assignment.question_type}</span>
              {assignment.has_code_question && <span className="pill bg-sky-900/50 text-sky-400">code question</span>}
              {assignment.deadline && (
                <span className="pill bg-surface-3 text-slate-400">
                  Due {new Date(assignment.deadline).toLocaleDateString()}
                </span>
              )}
            </div>
          </div>
          <Link
            href={`/assignments/${id}/upload`}
            className="px-4 py-2 rounded-xl bg-accent text-white text-sm font-semibold hover:bg-accent-dark transition-all shadow-md shadow-accent/25 flex-shrink-0"
          >
            + Upload Scans
          </Link>
        </div>

        {/* Progress bar */}
        {submissions.length > 0 && (
          <div className="mt-5">
            <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5">
              <span>Grading progress</span>
              <span>{statusCounts["graded"] ?? 0} / {submissions.length} graded</span>
            </div>
            <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
              <div
                className="h-1.5 rounded-full bg-gradient-to-r from-accent to-indigo-400 transition-all"
                style={{ width: `${((statusCounts["graded"] ?? 0) / submissions.length) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Stats + Rubric status */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total",      value: submissions.length,             color: "text-slate-100" },
          { label: "Graded",     value: statusCounts["graded"] ?? 0,    color: "text-success" },
          { label: "Processing", value: (statusCounts["processing"] ?? 0) + (statusCounts["grading"] ?? 0), color: "text-blue-400" },
          { label: "Failed",     value: statusCounts["failed"] ?? 0,    color: "text-danger" },
        ].map(s => (
          <div key={s.label} className="glass p-4">
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Rubric alert */}
      {!approvedRubric && (
        <div className="glass p-4 border border-amber-500/20 flex items-start gap-3">
          <span className="text-amber-400 text-lg flex-shrink-0">⚠</span>
          <div className="text-sm">
            <p className="font-medium text-amber-300">No approved rubric</p>
            <p className="text-slate-400 mt-0.5 text-xs">
              Grading will use a default rubric until you{" "}
              <Link href={`/assignments/${id}/rubric`} className="text-accent-light hover:underline">upload or generate one</Link>.
            </p>
          </div>
        </div>
      )}

      {/* Submissions table */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">Submissions</h2>
          {(statusCounts["graded"] ?? 0) > 0 && (
            <Link href={`/assignments/${id}/release`}
              className="text-xs px-3 py-1.5 rounded-lg bg-emerald-900/50 text-emerald-300 hover:bg-emerald-900/70 transition-colors border border-emerald-700/30">
              Release All Grades →
            </Link>
          )}
        </div>

        {submissions.length === 0 ? (
          <div className="glass p-12 text-center text-slate-500 text-sm">
            No submissions yet. Upload student scans to begin.
          </div>
        ) : (
          <div className="glass overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.06] text-xs text-slate-500 uppercase tracking-wider">
                  <th className="text-left px-4 py-3 font-medium">Student</th>
                  <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">Status</th>
                  <th className="text-left px-4 py-3 font-medium hidden md:table-cell">OCR Engine</th>
                  <th className="text-left px-4 py-3 font-medium">Submitted</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {submissions.map(s => (
                  <tr key={s.id} className="hover:bg-white/[0.02] transition-colors group">
                    <td className="px-4 py-3">
                      <p className="font-medium text-slate-200">{s.student_name ?? s.student_id}</p>
                      {s.student_name && <p className="text-[10px] text-slate-600">{s.student_id}</p>}
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell">
                      <StatusBadge status={s.status} />
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      {s.ocr_engine ? (
                        <span className="pill bg-surface-3 text-slate-400 text-[10px] uppercase">{s.ocr_engine}</span>
                      ) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">
                      {new Date(s.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/review/${s.id}`}
                        className="text-xs px-3 py-1.5 rounded-lg bg-surface-3 text-slate-400 hover:bg-accent hover:text-white transition-all opacity-0 group-hover:opacity-100"
                      >
                        Review →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
