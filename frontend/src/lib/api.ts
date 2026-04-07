// Centralised API client — all calls go through Next.js rewrite → backend:8080

const BASE = "/api/v1";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type QuestionType = "objective" | "subjective" | "mixed";
export type SubmissionStatus = "pending" | "processing" | "ocr_done" | "grading" | "graded" | "failed";
export type ClassroomStatus  = "not_synced" | "draft" | "released";
export type GradeSource      = "AI_Generated" | "AI_Corrected" | "AI_HEALED" | "TA_Manual";

export interface Assignment {
  id: string;
  course_id: string;
  classroom_id?: string;
  title: string;
  description?: string;
  deadline?: string;
  max_marks: number;
  question_type: QuestionType;
  has_code_question: boolean;
  created_at: string;
}

export interface OCRBlock {
  index: number;
  label: string;
  content: string;
  bbox_2d: [number, number, number, number] | null;
  confidence: number;
  flagged: boolean;
  error?: string;
  question?: string;
}

export interface Submission {
  id: string;
  assignment_id: string;
  student_id: string;
  student_name?: string;
  status: SubmissionStatus;
  ocr_result?: { blocks: OCRBlock[]; block_count: number; flagged_count: number; engine: string };
  ocr_engine?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface Grade {
  id: string;
  submission_id: string;
  active_version: boolean;
  total_score: number;
  breakdown_json: Record<string, { marks_awarded: number; max_marks: number; feedback: string; is_truncated: boolean }>;
  source: GradeSource;
  classroom_status: ClassroomStatus;
  is_truncated: boolean;
  graded_at: string;
}

export interface AuditLog {
  id: string;
  submission_id: string;
  changed_by: string;
  action: string;
  old_value_json?: Record<string, unknown>;
  new_value_json?: Record<string, unknown>;
  reason?: string;
  timestamp: string;
}

export interface Rubric {
  id: string;
  assignment_id: string;
  content_json: Record<string, unknown>;
  source: "manual" | "ai_generated";
  approved: boolean;
  approved_by?: string;
  created_at: string;
}

// ── Assignments ───────────────────────────────────────────────────────────────

export const api = {
  assignments: {
    list: (courseId?: string) =>
      req<Assignment[]>(`/assignments${courseId ? `?course_id=${courseId}` : ""}`),
    get: (id: string) => req<Assignment>(`/assignments/${id}`),
    create: (body: Partial<Assignment>) =>
      req<Assignment>("/assignments/", { method: "POST", body: JSON.stringify(body) }),
  },

  submissions: {
    list: (assignmentId: string, status?: SubmissionStatus) =>
      req<Submission[]>(`/submissions/${assignmentId}${status ? `?status=${status}` : ""}`),
    get: (id: string) => req<Submission>(`/submissions/detail/${id}`),
    grade: (submissionId: string) => req<Grade>(`/submissions/${submissionId}/grade`),
    audit: (submissionId: string) => req<AuditLog[]>(`/submissions/${submissionId}/audit`),
    correctOCR: (submissionId: string, blockIndex: number, newContent: string, reason?: string) =>
      req(`/submissions/${submissionId}/ocr-correction`, {
        method: "PATCH",
        body: JSON.stringify({ block_index: blockIndex, new_content: newContent, reason, changed_by: "ta" }),
      }),
  },

  rubrics: {
    list: (assignmentId: string) => req<Rubric[]>(`/rubrics/${assignmentId}`),
    upload: (assignmentId: string, contentJson: Record<string, unknown>) =>
      req<Rubric>(`/rubrics/${assignmentId}`, { method: "POST", body: JSON.stringify({ content_json: contentJson, source: "manual" }) }),
    generate: (assignmentId: string, masterAnswer: string) =>
      req<Rubric>(`/rubrics/${assignmentId}/generate`, { method: "POST", body: JSON.stringify({ master_answer: masterAnswer }) }),
    approve: (rubricId: string) =>
      req<Rubric>(`/rubrics/${rubricId}/approve`, { method: "POST", body: JSON.stringify({ approved_by: "ta" }) }),
  },

  grades: {
    releaseDraft: (submissionIds: string[]) =>
      req("/grades/draft", { method: "POST", body: JSON.stringify({ submission_ids: submissionIds }) }),
    releaseAssigned: (submissionIds: string[]) =>
      req("/grades/release", { method: "POST", body: JSON.stringify({ submission_ids: submissionIds }) }),
  },
};
