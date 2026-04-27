"use client";
import React, { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
    ArrowLeft, CheckCircle, XCircle, Clock, ChevronRight,
    Terminal, Zap, RefreshCw, AlertTriangle, Code2,
} from "lucide-react";
import { PageShell } from "@/components/layout/Shell";
import { api } from "@/lib/api";
import type { CodeEvalAttempt, JobStatus } from "@/lib/types";

const STATUS_CLASS: Record<string, string> = {
    QUEUED: "badge-default", EXECUTING_RAW: "badge-info", AI_ANALYZING: "badge-accent",
    RETRYING_SHIM: "badge-warning", FINALIZING: "badge-info",
    COMPLETED: "badge-success", FAILED: "badge-danger",
};

const STAGE_ICON: Record<string, React.ReactNode> = {
    raw_execution: <Terminal size={13} />,
    ai_analysis: <Zap size={13} />,
    shim_retry: <RefreshCw size={13} />,
    finalizing: <CheckCircle size={13} />,
    EXECUTING_RAW: <Terminal size={13} />,
    AI_ANALYZING: <Zap size={13} />,
    RETRYING_SHIM: <RefreshCw size={13} />,
    FINALIZING: <CheckCircle size={13} />,
};

function prettyStage(stage: string) {
    return stage.replace(/_/g, " ").toLowerCase();
}

function JobFinalResult({ result }: { result: Record<string, unknown> }) {
    const scoreBreakdown = result.score_breakdown as {
        correctness_score?: number;
        correctness_percent?: number;
        total_score?: number;
        total_percent?: number;
        max_score?: number;
        quality_applied?: boolean;
        quality_mode?: string;
    } | undefined;
    const status = typeof result.status === "string" ? result.status : "UNKNOWN";
    const errorCode = typeof result.error_code === "string" ? result.error_code : null;
    const failedCases = (
        (result.shim_decision as { failed_testcases?: Array<{ testcase_id?: string; decision_reason?: string; failure_tokens?: string[] }> } | undefined)?.failed_testcases
        ?? []
    );

    return (
        <div className="card" style={{ marginBottom: "var(--space-4)", padding: 0 }}>
            <div style={{ padding: "var(--space-4)", borderBottom: "1px solid var(--border)", fontSize: 13, fontWeight: 600 }}>
                Final Result
            </div>
            <div style={{ padding: "var(--space-4)", display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                    <span className={`badge ${status === "COMPLETED" ? "badge-success" : status === "FAILED" ? "badge-danger" : "badge-default"}`}>
                        {status}
                    </span>
                    {errorCode && <span className="badge badge-warning">{errorCode}</span>}
                </div>

                {scoreBreakdown && (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "var(--space-3)" }}>
                        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)" }}>
                            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Correctness</div>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>
                                {scoreBreakdown.correctness_score ?? 0}
                                {scoreBreakdown.max_score !== undefined ? ` / ${scoreBreakdown.max_score}` : ""}
                            </div>
                            {scoreBreakdown.correctness_percent !== undefined && (
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{scoreBreakdown.correctness_percent}%</div>
                            )}
                        </div>
                        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)" }}>
                            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>Total</div>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>
                                {scoreBreakdown.total_score ?? 0}
                                {scoreBreakdown.max_score !== undefined ? ` / ${scoreBreakdown.max_score}` : ""}
                            </div>
                            {scoreBreakdown.total_percent !== undefined && (
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{scoreBreakdown.total_percent}%</div>
                            )}
                        </div>
                    </div>
                )}

                {failedCases.length > 0 && (
                    <div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: "var(--space-2)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                            Failed Testcases
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {failedCases.map((tc, idx) => (
                                <div
                                    key={`${tc.testcase_id ?? "case"}-${idx}`}
                                    style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-base)" }}
                                >
                                    <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{tc.testcase_id ?? "unknown_case"}</div>
                                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                                        {[tc.decision_reason, ...(tc.failure_tokens ?? [])].filter(Boolean).join(" · ") || "mismatch"}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                <details>
                    <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--text-muted)" }}>
                        View raw JSON
                    </summary>
                    <pre style={{ marginTop: "var(--space-2)", padding: "var(--space-3)", fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", background: "var(--bg-base)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "auto", maxHeight: 320 }}>
                        {JSON.stringify(result, null, 2)}
                    </pre>
                </details>
            </div>
        </div>
    );
}

function AttemptCard({ attempt, index }: { attempt: CodeEvalAttempt; index: number }) {
    const [expanded, setExpanded] = useState(index === 0);
    const duration = attempt.started_at && attempt.finished_at
        ? ((new Date(attempt.finished_at).getTime() - new Date(attempt.started_at).getTime()) / 1000).toFixed(2)
        : null;

    return (
        <div style={{
            border: `1px solid ${attempt.passed ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`,
            borderRadius: "var(--radius-lg)",
            overflow: "hidden",
            background: "var(--bg-card)",
        }}>
            {/* Header */}
            <button
                onClick={() => setExpanded(e => !e)}
                style={{
                    width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "var(--space-3) var(--space-4)", background: "transparent",
                    border: "none", cursor: "pointer", textAlign: "left",
                }}
            >
                <div className="flex items-center gap-3">
                    {attempt.passed
                        ? <CheckCircle size={16} style={{ color: "var(--success)" }} />
                        : <XCircle size={16} style={{ color: "var(--danger)" }} />}
                    <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                        Attempt #{attempt.attempt_index + 1}
                    </span>
                    <span style={{
                        fontSize: 11, padding: "2px 8px", borderRadius: "var(--radius-full)",
                        background: "var(--bg-elevated)", color: "var(--text-muted)",
                    }}>
                        {STAGE_ICON[attempt.stage] ?? <Code2 size={11} />}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        {prettyStage(attempt.stage)}
                    </span>
                    {attempt.shim_used && (
                        <span className="badge badge-warning" style={{ fontSize: 10 }}>
                            Shim · {attempt.shim_source}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-4">
                    <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>
                        Score: {attempt.score}
                    </span>
                    {attempt.exit_code !== null && (
                        <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                            exit {attempt.exit_code}
                        </span>
                    )}
                    {duration && (
                        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{duration}s</span>
                    )}
                    <ChevronRight size={14} style={{
                        color: "var(--text-muted)", transform: expanded ? "rotate(90deg)" : "none",
                        transition: "transform 0.2s",
                    }} />
                </div>
            </button>

            {/* Expanded body */}
            {expanded && (
                <div style={{ borderTop: "1px solid var(--border)", padding: "var(--space-4)" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                        {/* stdout */}
                        <div>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: "var(--space-2)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                                stdout
                            </div>
                            <pre style={{
                                background: "var(--bg-base)", border: "1px solid var(--border)",
                                borderRadius: "var(--radius-sm)", padding: "var(--space-3)",
                                fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)",
                                overflow: "auto", maxHeight: 200, margin: 0,
                                whiteSpace: "pre-wrap", wordBreak: "break-all",
                            }}>
                                {attempt.stdout || "(empty)"}
                            </pre>
                        </div>
                        {/* stderr */}
                        <div>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: "var(--space-2)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                                stderr
                            </div>
                            <pre style={{
                                background: "var(--bg-base)", border: "1px solid var(--border)",
                                borderRadius: "var(--radius-sm)", padding: "var(--space-3)",
                                fontSize: 11, fontFamily: "var(--font-mono)",
                                color: attempt.stderr ? "rgba(239,68,68,0.9)" : "var(--text-muted)",
                                overflow: "auto", maxHeight: 200, margin: 0,
                                whiteSpace: "pre-wrap", wordBreak: "break-all",
                            }}>
                                {attempt.stderr || "(empty)"}
                            </pre>
                        </div>
                    </div>

                    {/* Artifacts */}
                    {attempt.artifacts_json && Object.keys(attempt.artifacts_json).length > 0 && (
                        <div style={{ marginTop: "var(--space-3)" }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: "var(--space-2)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                                Artifacts
                            </div>
                            {Array.isArray((attempt.artifacts_json as Record<string, unknown>).testcases) ? (
                                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                    {((attempt.artifacts_json as Record<string, unknown>).testcases as Array<{ testcase_id?: string; passed?: boolean; awarded_score?: number; weight?: number; failure_reason?: string | null }>).map((tc, idx) => (
                                        <div
                                            key={`${tc.testcase_id ?? "test"}-${idx}`}
                                            style={{ border: `1px solid ${tc.passed ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`, borderRadius: "var(--radius-sm)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-base)" }}
                                        >
                                            <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)" }}>
                                                <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>
                                                    {tc.testcase_id ?? "unknown_case"}
                                                </span>
                                                <span style={{ fontSize: 11, fontWeight: 600, color: tc.passed ? "var(--success)" : "var(--danger)" }}>
                                                    {(tc.awarded_score ?? 0)}/{tc.weight ?? 0}
                                                </span>
                                            </div>
                                            {!tc.passed && tc.failure_reason && (
                                                <div style={{ fontSize: 11, color: "var(--danger)", marginTop: 2 }}>
                                                    {tc.failure_reason}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                    <details>
                                        <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--text-muted)" }}>View raw artifacts</summary>
                                        <pre style={{ marginTop: "var(--space-2)", background: "var(--bg-base)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-3)", fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", overflow: "auto", maxHeight: 220 }}>
                                            {JSON.stringify(attempt.artifacts_json, null, 2)}
                                        </pre>
                                    </details>
                                </div>
                            ) : (
                                <pre style={{
                                    background: "var(--bg-base)", border: "1px solid var(--border)",
                                    borderRadius: "var(--radius-sm)", padding: "var(--space-3)",
                                    fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)",
                                    overflow: "auto", maxHeight: 200, margin: 0,
                                }}>
                                    {JSON.stringify(attempt.artifacts_json, null, 2)}
                                </pre>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default function CodeEvalJobDetailPage() {
    const { id } = useParams<{ id: string }>();
    const router = useRouter();

    const { data: job, isLoading } = useQuery({
        queryKey: ["code-eval-job", id],
        queryFn: () => api.codeEval.jobs.get(id),
        refetchInterval: (q) => {
            const s = q.state.data?.status as JobStatus | undefined;
            return s && !["COMPLETED", "FAILED"].includes(s) ? 2500 : false;
        },
    });

    if (isLoading) {
        return (
            <PageShell>
                <div className="flex flex-col gap-4">
                    {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 80, borderRadius: "var(--radius-lg)" }} />)}
                </div>
            </PageShell>
        );
    }

    if (!job) {
        return (
            <PageShell>
                <div className="empty-state">
                    <AlertTriangle size={40} className="empty-icon" />
                    <div className="empty-title">Job not found</div>
                    <button className="btn btn-secondary" onClick={() => router.back()}>Go back</button>
                </div>
            </PageShell>
        );
    }

    const isActive = !["COMPLETED", "FAILED"].includes(job.status);
    const duration = job.started_at && job.finished_at
        ? ((new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000).toFixed(1)
        : null;

    return (
        <PageShell>
            <div className="animate-fade-up">
                {/* Breadcrumb */}
                <div className="flex items-center gap-2" style={{ marginBottom: "var(--space-4)", fontSize: 13, color: "var(--text-muted)" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => router.push("/code-eval/jobs")}>
                        <ArrowLeft size={13} /> Code Eval Jobs
                    </button>
                    <ChevronRight size={13} />
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)", fontSize: 12 }}>
                        {id.slice(0, 16)}…
                    </span>
                    {isActive && (
                        <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--warning)" }}>
                            <RefreshCw size={11} style={{ animation: "spin 1.5s linear infinite" }} />
                            Live
                        </span>
                    )}
                </div>

                {/* Header */}
                <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-6)" }}>
                    <div>
                        <div className="flex items-center gap-3">
                            <h1 className="page-title">Job Detail</h1>
                            <span className={`badge ${STATUS_CLASS[job.status]}`}>{job.status.replace(/_/g, " ")}</span>
                        </div>
                        <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>
                            {job.language} · {job.entrypoint} · {job.attempt_count} attempt{job.attempt_count !== 1 ? "s" : ""}
                            {duration && ` · ${duration}s total`}
                        </div>
                    </div>
                </div>

                {/* Meta grid */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-3)", marginBottom: "var(--space-6)" }}>
                    {[
                        { label: "Assignment", value: job.assignment_id.slice(0, 8) + "…" },
                        { label: "Submission", value: job.submission_id.slice(0, 8) + "…" },
                        { label: "Env Version", value: job.environment_version_id ? job.environment_version_id.slice(0, 8) + "…" : "—" },
                        { label: "Regrade Policy", value: job.regrade_policy.replace(/_/g, " ") },
                    ].map(({ label, value }) => (
                        <div key={label} className="card" style={{ padding: "var(--space-3) var(--space-4)" }}>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{value}</div>
                        </div>
                    ))}
                </div>

                {/* Final result */}
                {job.final_result_json && <JobFinalResult result={job.final_result_json} />}

                {/* Error */}
                {job.error_message && (
                    <div style={{
                        padding: "var(--space-4)", borderRadius: "var(--radius-lg)",
                        background: "var(--danger-dim)", border: "1px solid rgba(239,68,68,0.3)",
                        marginBottom: "var(--space-4)", fontSize: 13, color: "var(--danger)", fontFamily: "var(--font-mono)",
                    }}>
                        <strong>Error:</strong> {job.error_message}
                    </div>
                )}

                {/* Attempts */}
                <div style={{ marginBottom: "var(--space-2)", fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                    Execution Attempts ({job.attempts.length})
                </div>
                {job.attempts.length === 0 ? (
                    <div className="empty-state" style={{ minHeight: 120 }}>
                        <Clock size={32} className="empty-icon" />
                        <div className="empty-title">No attempts yet</div>
                        <div className="empty-message">The job is queued and will start shortly.</div>
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        {job.attempts.map((attempt, i) => (
                            <AttemptCard key={attempt.id} attempt={attempt} index={i} />
                        ))}
                    </div>
                )}
            </div>

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </PageShell>
    );
}
