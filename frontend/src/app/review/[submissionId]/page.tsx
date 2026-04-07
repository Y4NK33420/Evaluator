import { api } from "@/lib/api";
import { notFound } from "next/navigation";
import SplitScreenReview from "@/components/SplitScreenReview";
import type { Metadata } from "next";

interface Props { params: Promise<{ submissionId: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { submissionId } = await params;
  try {
    const s = await api.submissions.get(submissionId);
    return { title: `AMGS — Review ${s.student_name ?? s.student_id}` };
  } catch { return { title: "Review" }; }
}

export const revalidate = 0; // always fresh — TA is actively working

export default async function ReviewPage({ params }: Props) {
  const { submissionId } = await params;

  let submission: Awaited<ReturnType<typeof api.submissions.get>>;
  try { submission = await api.submissions.get(submissionId); }
  catch { notFound(); }

  const assignment = await api.assignments.get(submission.assignment_id).catch(() => null);
  if (!assignment) notFound();

  const grade    = await api.submissions.grade(submissionId).catch(() => null);
  const auditLog = await api.submissions.audit(submissionId).catch(() => []);

  return (
    <SplitScreenReview
      submission={submission}
      assignment={assignment}
      initialGrade={grade}
      initialAudit={auditLog}
    />
  );
}
