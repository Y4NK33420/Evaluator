// ── Enums (mirror backend) ─────────────────────────────────────────────────

export type QuestionType = "objective" | "subjective" | "mixed";
export type SubmissionStatus = "pending" | "processing" | "ocr_done" | "grading" | "graded" | "failed";
export type GradeSource = "AI_Generated" | "AI_Corrected" | "AI_HEALED" | "TA_Manual" | "code_eval";
export type ClassroomStatus = "not_synced" | "draft" | "released";
export type RubricSource = "manual" | "ai_generated";
export type JobStatus = "QUEUED" | "EXECUTING_RAW" | "AI_ANALYZING" | "RETRYING_SHIM" | "FINALIZING" | "COMPLETED" | "FAILED";
export type EnvStatus = "draft" | "building" | "ready" | "failed" | "deprecated";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type ApprovalType = "ai_solution" | "ai_tests" | "ai_quality_rubric";

// ── Core models ────────────────────────────────────────────────────────────

export interface Assignment {
    id: string;
    course_id: string;
    classroom_id: string | null;
    title: string;
    description: string | null;
    deadline: string | null;
    max_marks: number;
    question_type: QuestionType;
    has_code_question: boolean;
    is_published: boolean;
    published_at: string | null;
    published_by: string | null;
    published_environment_version_id: string | null;
    created_at: string;
    updated_at: string;
}

export interface AssignmentSummary extends Assignment {
    submission_count: number;
    graded_count: number;
    released_count: number;
    error_count: number;
}

export interface Submission {
    id: string;
    assignment_id: string;
    student_id: string;
    student_name: string | null;
    status: SubmissionStatus;
    ocr_result: OcrResult | null;
    ocr_engine: string | null;
    error_message: string | null;
    created_at: string;
    updated_at: string;
    // Enriched fields (from /submissions/detail/{id} full version)
    assignment_max_marks?: number;
    assignment_title?: string;
}

export interface OcrResult {
    blocks: OcrBlock[];
    flagged_count?: number;
    [key: string]: unknown;
}

export interface OcrBlock {
    index: number;
    content: string;
    bbox?: [number, number, number, number]; // [x, y, w, h] normalised 0-1
    confidence?: number;
    flagged?: boolean;
}

export interface Rubric {
    id: string;
    assignment_id: string;
    content_json: RubricContent;
    source: RubricSource;
    approved: boolean;
    approved_by: string | null;
    created_at: string;
}

export interface RubricContent {
    questions?: RubricQuestion[];
    scoring_policy?: {
        coding?: { rubric_weight: number; testcase_weight: number };
    };
    [key: string]: unknown;
}

export interface RubricQuestion {
    id?: string | number;
    name?: string;
    marks?: number;
    max_marks?: number;
    criteria?: string;
    [key: string]: unknown;
}

export interface Grade {
    id: string;
    submission_id: string;
    active_version: boolean;
    total_score: number;
    breakdown_json: GradeBreakdown;
    source: GradeSource;
    classroom_status: ClassroomStatus;
    is_truncated: boolean;
    graded_at: string;
}

export interface GradeBreakdown {
    [questionKey: string]: {
        marks: number;
        feedback: string;
        max_marks?: number;
    };
}

export interface AuditLog {
    id: string;
    submission_id: string;
    changed_by: string;
    action: string;
    old_value_json: Record<string, unknown> | null;
    new_value_json: Record<string, unknown> | null;
    reason: string | null;
    timestamp: string;
}

export interface EnvironmentVersion {
    id: string;
    course_id: string;
    assignment_id: string | null;
    profile_key: string;
    reuse_mode: string;
    spec_json: Record<string, unknown>;
    freeze_key: string | null;
    status: EnvStatus;
    version_number: number;
    is_active: boolean;
    build_logs: string | null;
    created_by: string | null;
    created_at: string;
    updated_at: string;
}

export interface ApprovalItem {
    id: string;
    assignment_id: string;
    artifact_type: ApprovalType;
    status: ApprovalStatus;
    version_number: number;
    content_json: Record<string, unknown> | null;
    generation_metadata_json: Record<string, unknown> | null;
    requested_by: string | null;
    approved_by: string | null;
    approved_at: string | null;
    rejected_reason: string | null;
    created_at: string;
    updated_at: string;
}

export interface CodeEvalJob {
    id: string;
    assignment_id: string;
    submission_id: string;
    environment_version_id: string | null;
    status: JobStatus;
    language: string;
    entrypoint: string;
    regrade_policy: string;
    explicit_regrade: boolean;
    attempt_count: number;
    final_result_json: Record<string, unknown> | null;
    error_message: string | null;
    queued_at: string;
    started_at: string | null;
    finished_at: string | null;
    created_at: string;
    updated_at: string;
}

export interface CodeEvalAttempt {
    id: string;
    job_id: string;
    attempt_index: number;
    stage: string;
    passed: boolean;
    exit_code: number | null;
    score: number;
    stdout: string;
    stderr: string;
    shim_used: boolean;
    shim_source: string | null;
    artifacts_json: Record<string, unknown> | null;
    started_at: string | null;
    finished_at: string | null;
    created_at: string;
}

export interface CodeEvalJobDetail extends CodeEvalJob {
    attempts: CodeEvalAttempt[];
}

export interface RuntimeStatus {
    execution_backend: string;
    shim_retry_enabled: boolean;
    ai_shim_generation_enabled: boolean;
    microvm: Record<string, unknown>;
}

export interface ClassroomAuthStatus {
    authenticated: boolean;
    // When authenticated:
    valid?: boolean;
    expired?: boolean;
    has_refresh_token?: boolean;
    scopes?: string[];
    friendly_scopes?: string[];
    // When not authenticated:
    reason?: string;        // "token_missing" | error string
    token_path?: string;
    credentials_file_exists?: boolean;
}

export interface HealthResponse {
    status: string;
    service: string;
}

export interface SyncSummary {
    assignment_id: string;
    found: number;
    ingested: number;
    pushed: number;
    released: number;
    skipped: number;
    errors: unknown[];
    status: string;
}

export interface PublishValidation {
    assignment_id: string;
    ready_for_publish: boolean;
    checks: Record<string, boolean>;
    missing: string[];
    environment_version_id: string | null;
}

// ── UI helpers ─────────────────────────────────────────────────────────────

export type ToastVariant = "success" | "error" | "warning" | "info";

export interface Toast {
    id: string;
    variant: ToastVariant;
    title: string;
    message?: string;
}

export interface NavSection {
    label: string;
    items: NavItem[];
}

export interface NavItem {
    label: string;
    href: string;
    icon: React.ComponentType<{ size?: number; className?: string }>;
    badge?: number;
}
