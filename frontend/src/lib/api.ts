import type {
    ApprovalItem, Assignment, AssignmentSummary, ClassroomAuthStatus,
    CodeEvalJob, CodeEvalJobDetail, EnvironmentVersion, Grade,
    HealthResponse, PublishValidation, RuntimeStatus, Rubric,
    Submission, SyncSummary,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";
const API_PREFIX = "/api/v1";

export class ApiError extends Error {
    constructor(public status: number, message: string) {
        super(message);
        this.name = "ApiError";
    }
}

async function fetchJson<T>(url: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(url, options);
    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText })) as { detail?: string | object };
        const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        throw new ApiError(res.status, detail || "Unknown error");
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
}

function toUrl(path: string, params?: Record<string, string | number | boolean | undefined | null>) {
    const full = path.startsWith(API_PREFIX) ? path : `${API_PREFIX}${path}`;
    const url = new URL(`${API_BASE}${full}`);
    if (params) {
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
        });
    }
    return url.toString();
}

interface ApiOptions extends Omit<RequestInit, "body"> {
    params?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
    const { params, body, headers, ...rest } = opts;
    const h = new Headers(headers);
    let payload: BodyInit | undefined;
    if (body instanceof FormData) {
        payload = body;
    } else if (body !== undefined) {
        h.set("Content-Type", "application/json");
        payload = JSON.stringify(body);
    }
    return fetchJson<T>(toUrl(path, params), { ...rest, headers: h, body: payload });
}

// ── Export direct URL builder (for file downloads / images) ───────────────
export const buildUrl = (path: string, params?: Record<string, string>) =>
    toUrl(path, params);

// ── API client ─────────────────────────────────────────────────────────────
export const api = {
    health: {
        get: () => fetchJson<HealthResponse>(`${API_BASE}/health`),
    },

    // ── Assignments ──────────────────────────────────────────────────────────
    assignments: {
        list: () => apiFetch<Assignment[]>("/assignments/"),
        get: (id: string) => apiFetch<Assignment>(`/assignments/${id}`),
        create: (p: Partial<Assignment>) => apiFetch<Assignment>("/assignments/", { method: "POST", body: p }),
        update: (id: string, p: Partial<Assignment>) =>
            apiFetch<Assignment>(`/assignments/${id}`, { method: "PATCH", body: p }),
        remove: (id: string) => apiFetch<void>(`/assignments/${id}`, { method: "DELETE" }),
        validatePublish: (id: string, env_version_id?: string) =>
            apiFetch<PublishValidation>(`/assignments/${id}/validate-publish`, {
                method: "POST",
                body: { environment_version_id: env_version_id ?? null },
            }),
        publish: (id: string, actor: string, env_version_id?: string, force = false) =>
            apiFetch<{ assignment: Assignment; validation: PublishValidation }>(
                `/assignments/${id}/publish`,
                { method: "POST", body: { actor, environment_version_id: env_version_id ?? null, force_republish: force } }
            ),
        // New: grade CSV download (use window.location)
        gradesCSVUrl: (id: string) => buildUrl(`/assignments/${id}/grades/csv`),
        // New: summary list endpoint (falls back to plain list if 404)
        listSummary: () => apiFetch<AssignmentSummary[]>("/assignments/summary").catch(() =>
            apiFetch<Assignment[]>("/assignments/").then(list => list.map(a => ({
                ...a, submission_count: 0, graded_count: 0, released_count: 0, error_count: 0
            } as AssignmentSummary)))
        ),
    },

    // ── Submissions ──────────────────────────────────────────────────────────
    submissions: {
        listByAssignment: (assignmentId: string, status?: string) =>
            apiFetch<Submission[]>(`/submissions/${assignmentId}`, { params: { status } }),
        listAll: (params?: { status?: string; limit?: number; offset?: number }) =>
            apiFetch<Submission[]>("/submissions/", { params }),
        detail: (id: string) => apiFetch<Submission>(`/submissions/detail/${id}`),
        grade: (id: string) => apiFetch<Grade>(`/submissions/${id}/grade`),
        audit: (id: string) => apiFetch<{ id: string; action: string; changed_by: string; reason: string | null; old_value_json: Record<string, unknown> | null; new_value_json: Record<string, unknown> | null; timestamp: string }[]>(`/submissions/${id}/audit`),
        correctOcr: (id: string, payload: { block_index: number; new_content: string; reason?: string; changed_by: string }) =>
            apiFetch<{ job_id: string; submission_id: string; status: string }>(`/submissions/${id}/ocr-correction`, { method: "PATCH", body: payload }),
        upload: (assignmentId: string, payload: { student_id: string; student_name?: string; file: File }) => {
            const form = new FormData();
            form.append("file", payload.file);
            return apiFetch<{ job_id: string; submission_id: string }>(`/submissions/${assignmentId}/upload`, {
                method: "POST", body: form,
                params: { student_id: payload.student_id, student_name: payload.student_name },
            });
        },
        regrade: (id: string, reason: string, changed_by: string) =>
            apiFetch<{ job_id: string; submission_id: string; status: string }>(`/submissions/${id}/regrade`, {
                method: "POST", body: { reason, changed_by },
            }),
        overrideGrade: (id: string, payload: { total_score: number; breakdown_json: Record<string, unknown>; reason: string; changed_by: string }) =>
            apiFetch<Grade>(`/submissions/${id}/grade-override`, { method: "POST", body: payload }),
        imageUrl: (id: string) => buildUrl(`/submissions/image/${id}`),
        dispatchCodeEval: (id: string, opts?: { explicit_regrade?: boolean; changed_by?: string }) =>
            apiFetch<{ job_id: string; submission_id: string; status: string }>(`/submissions/${id}/dispatch-code-eval`, {
                method: "POST",
                params: { explicit_regrade: opts?.explicit_regrade ?? false, changed_by: opts?.changed_by ?? "ta" },
            }),
    },

    // ── Grades ───────────────────────────────────────────────────────────────
    grades: {
        pushDraft: (ids: string[]) => apiFetch<{ synced_as_draft: string[]; errors: unknown[] }>("/grades/draft", { method: "POST", body: { submission_ids: ids } }),
        release: (ids: string[]) => apiFetch<{ released: string[]; errors: unknown[] }>("/grades/release", { method: "POST", body: { submission_ids: ids } }),
    },

    // ── Rubrics ──────────────────────────────────────────────────────────────
    rubrics: {
        listForAssignment: (assignmentId: string) => apiFetch<Rubric[]>(`/rubrics/${assignmentId}`),
        getForAssignment: async (assignmentId: string) => {
            const list = await apiFetch<Rubric[]>(`/rubrics/${assignmentId}`);
            return list.length ? list[0] : null;
        },
        create: (assignmentId: string, content_json: Record<string, unknown>) =>
            apiFetch<Rubric>(`/rubrics/${assignmentId}`, { method: "POST", body: { content_json, source: "manual" } }),
        generate: (assignmentId: string, assignmentText: string) =>
            apiFetch<Rubric>(`/rubrics/${assignmentId}/generate`, { method: "POST", body: { assignment_text: assignmentText } }),
        encodeNaturalLanguage: (assignmentId: string, naturalLanguageRubric: string) =>
            apiFetch<Rubric>(`/rubrics/${assignmentId}/encode-natural-language`, { method: "POST", body: { natural_language_rubric: naturalLanguageRubric } }),
        approve: (rubricId: string, actor: string) =>
            apiFetch<Rubric>(`/rubrics/${rubricId}/approve`, { method: "POST", body: { approved_by: actor } }),
        update: (rubricId: string, content_json: Record<string, unknown>) =>
            apiFetch<Rubric>(`/rubrics/${rubricId}`, { method: "PATCH", body: { content_json } }),
        remove: (rubricId: string) =>
            apiFetch<void>(`/rubrics/${rubricId}`, { method: "DELETE" }),
        listAll: (assignmentId: string) =>
            apiFetch<Rubric[]>(`/rubrics/${assignmentId}`),
    },

    // ── Classroom ─────────────────────────────────────────────────────────────
    classroom: {
        authStatus: () => apiFetch<ClassroomAuthStatus>("/classroom/auth-status"),
        generateToken: () => apiFetch<ClassroomAuthStatus>("/classroom/generate-token", { method: "POST" }),
        status: (assignmentId: string) => apiFetch<SyncSummary & { submissions: unknown[] }>(`/classroom/${assignmentId}/status`),
        ingest: (assignmentId: string, payload: { course_id: string; coursework_id: string; force_reingest?: boolean }) =>
            apiFetch<SyncSummary>(`/classroom/${assignmentId}/ingest`, { method: "POST", body: payload }),
        syncDraft: (assignmentId: string) => apiFetch<SyncSummary>(`/classroom/${assignmentId}/sync-draft`, { method: "POST" }),
        release: (assignmentId: string) => apiFetch<SyncSummary>(`/classroom/${assignmentId}/release`, { method: "POST" }),
    },

    // ── Code Eval ─────────────────────────────────────────────────────────────
    codeEval: {
        runtimeStatus: () => apiFetch<RuntimeStatus>("/code-eval/runtime/status"),
        runtimePreflight: () => apiFetch<Record<string, unknown>>("/code-eval/runtime/preflight"),

        environments: {
            list: (params?: { course_id?: string; assignment_id?: string; status?: string }) =>
                apiFetch<EnvironmentVersion[]>("/code-eval/environments/versions", { params }),
            get: (id: string) => apiFetch<EnvironmentVersion>(`/code-eval/environments/versions/${id}`),
            create: (payload: Record<string, unknown>) =>
                apiFetch<EnvironmentVersion>("/code-eval/environments/versions", { method: "POST", body: payload }),
            build: (id: string, actor: string, force = false) =>
                apiFetch<{ status: string; environment_version: EnvironmentVersion }>(
                    `/code-eval/environments/versions/${id}/build`,
                    { method: "POST", body: { triggered_by: actor, force_rebuild: force } }
                ),
            validatePublish: (id: string) =>
                apiFetch<Record<string, unknown>>(`/code-eval/environments/versions/${id}/validate-publish`, { method: "POST" }),
        },

        approvals: {
            list: (assignmentId: string) =>
                apiFetch<ApprovalItem[]>("/code-eval/approvals", { params: { assignment_id: assignmentId } }),
            create: (payload: { assignment_id: string; artifact_type: string; content_json: unknown; status: string; approved_by?: string }) =>
                apiFetch<ApprovalItem>("/code-eval/approvals", { method: "POST", body: payload }),
            approve: (id: string, actor: string, reason?: string) =>
                apiFetch<ApprovalItem>(`/code-eval/approvals/${id}/approve`, { method: "POST", body: { actor, reason } }),
            reject: (id: string, actor: string, reason: string) =>
                apiFetch<ApprovalItem>(`/code-eval/approvals/${id}/reject`, { method: "POST", body: { actor, reason } }),
            generateTests: (id: string, payload: {
                question_text: string; solution_code?: string;
                language: string; entrypoint: string; num_cases?: number; mode?: "mode2" | "mode3";
            }) => apiFetch<Record<string, unknown>>(`/code-eval/approvals/${id}/generate-tests`, { method: "POST", body: payload }),
        },

        jobs: {
            list: (params?: { assignment_id?: string; submission_id?: string; status?: string }) =>
                apiFetch<CodeEvalJob[]>("/code-eval/jobs", { params }),
            get: (id: string) => apiFetch<CodeEvalJobDetail>(`/code-eval/jobs/${id}`),
        },
    },
};
