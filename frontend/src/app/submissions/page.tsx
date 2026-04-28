"use client";
import React, { useState, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
    Upload, Search, CheckCircle, XCircle, RefreshCw,
    FileText, X, ChevronRight, Download, Send, AlertTriangle,
    Plus, Users, Code2, Trash2,
} from "lucide-react";
import { PageShell, Sidebar } from "@/components/layout/Shell";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import type { Submission, SubmissionStatus, Assignment } from "@/lib/types";

const SIDEBAR_ITEMS = [
    { href: "/submissions", label: "All Submissions", icon: FileText },
    { href: "/submissions/upload", label: "Upload Files", icon: Upload },
];

// ── Status helpers ──────────────────────────────────────────────────────────

const STATUS_LABEL: Record<SubmissionStatus, string> = {
    pending: "Pending OCR",
    processing: "Processing",
    ocr_done: "OCR Done",
    grading: "Grading",
    graded: "Graded",
    failed: "Failed",
};

const STATUS_CLASS: Record<SubmissionStatus, string> = {
    pending: "badge-default",
    processing: "badge-warning",
    ocr_done: "badge-info",
    grading: "badge-accent",
    graded: "badge-success",
    failed: "badge-danger",
};

// ── Upload panel ───────────────────────────────────────────────────────────

interface RosterEntry { student_id: string; student_name: string; }

function UploadPanel({
    assignments,
    initialAssignmentId,
    onClose,
}: { assignments: Assignment[]; initialAssignmentId?: string; onClose: () => void }) {
    const { toast } = useToast();
    const [uploadMode, setUploadMode] = useState<"batch" | "single">("batch");
    const [rosterMode, setRosterMode] = useState<"csv" | "classroom">("classroom");
    const [selectedAssignment, setSelectedAssignment] = useState(initialAssignmentId ?? "");
    const [roster, setRoster] = useState<RosterEntry[]>([]);
    const [files, setFiles] = useState<File[]>([]);
    const [progresses, setProgresses] = useState<Record<string, "uploading" | "done" | "error">>({});
    const fileInputRef = useRef<HTMLInputElement>(null);
    const singleFileRef = useRef<HTMLInputElement>(null);
    const qc = useQueryClient();

    // Single upload state
    const [singleStudentId, setSingleStudentId] = useState("");
    const [singleStudentName, setSingleStudentName] = useState("");
    const [singleFile, setSingleFile] = useState<File | null>(null);
    const [singleUploading, setSingleUploading] = useState(false);

    // Determine if selected assignment is coding
    const selectedAssignmentObj = assignments.find(a => a.id === selectedAssignment);
    const classroomCourseId = (selectedAssignmentObj?.course_id || "").replace(/^classroom-/, "").trim();
    const isCodingAssignment = selectedAssignmentObj?.has_code_question ?? false;
    const hasClassroomCourse = /^[0-9]{6,}$/.test(classroomCourseId);

    const { data: classroomStudents, refetch: refetchClassroomStudents, isFetching: rosterLoading } = useQuery({
        queryKey: ["classroom-roster", classroomCourseId],
        queryFn: async () => {
            if (!classroomCourseId) return [];
            const res = await api.classroom.listStudents(classroomCourseId);
            return res.students;
        },
        enabled: rosterMode === "classroom" && !!classroomCourseId,
    });

    // File accept strings
    const docAccept = ".pdf,.jpg,.jpeg,.png";
    const codeAccept = ".py,.java,.cpp,.c,.js,.ts,.go,.rs,.zip";
    const fileAccept = isCodingAssignment ? codeAccept : docAccept;
    const fileHint = isCodingAssignment
        ? "Code files (.py, .java, .cpp, .js, .go, .zip). Name by student ID (e.g. 21CS001.py)"
        : "PDFs/images. Name by student ID (e.g. 21CS001.pdf)";

    const parseRosterCSV = (text: string) => {
        const lines = text.trim().split("\n").slice(1);
        return lines.map(l => {
            const [id, name] = l.split(",").map(s => s.trim());
            return { student_id: id, student_name: name ?? "" };
        }).filter(r => r.student_id);
    };

    const handleRosterFile = (f: File) => {
        const reader = new FileReader();
        reader.onload = e => {
            const entries = parseRosterCSV(e.target?.result as string);
            setRoster(entries);
            toast("success", `Roster loaded`, `${entries.length} students`);
        };
        reader.readAsText(f);
    };

    const matchFile = (file: File): RosterEntry | null => {
        const base = file.name.replace(/\.[^.]+$/, "");
        if (rosterMode === "classroom") {
            const norm = base.toLowerCase().replace(/[^a-z0-9]+/g, "");
            const byId = roster.find(r => r.student_id === base);
            if (byId) return byId;
            return roster.find(r => (r.student_name || "").toLowerCase().replace(/[^a-z0-9]+/g, "") === norm) ?? null;
        }
        return roster.find(r => r.student_id === base) ?? null;
    };

    const uploadAll = async () => {
        if (!selectedAssignment) { toast("error", "Select an assignment first"); return; }
        const tasks = files.map(async file => {
            const match = matchFile(file);
            if (!match) { setProgresses(p => ({ ...p, [file.name]: "error" })); return; }
            setProgresses(p => ({ ...p, [file.name]: "uploading" }));
            try {
                await api.submissions.upload(selectedAssignment, {
                    student_id: match.student_id,
                    student_name: match.student_name,
                    file,
                });
                setProgresses(p => ({ ...p, [file.name]: "done" }));
            } catch {
                setProgresses(p => ({ ...p, [file.name]: "error" }));
            }
        });
        await Promise.allSettled(tasks);
        qc.invalidateQueries({ queryKey: ["submissions"] });
        toast("success", "Upload complete");
    };

    const uploadSingle = async () => {
        if (!selectedAssignment) { toast("error", "Select an assignment first"); return; }
        if (!singleStudentId.trim()) { toast("error", "Enter a Student ID"); return; }
        if (!singleFile) { toast("error", "Select a file to upload"); return; }
        setSingleUploading(true);
        try {
            await api.submissions.upload(selectedAssignment, {
                student_id: singleStudentId.trim(),
                student_name: singleStudentName.trim() || singleStudentId.trim(),
                file: singleFile,
            });
            qc.invalidateQueries({ queryKey: ["submissions"] });
            toast("success", "Submission uploaded!", `${singleStudentName || singleStudentId}`);
            setSingleStudentId(""); setSingleStudentName(""); setSingleFile(null);
            onClose();
        } catch (e: unknown) {
            toast("error", "Upload failed", (e as Error).message);
        } finally {
            setSingleUploading(false);
        }
    };

    return (
        <div style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 800,
            display: "flex", alignItems: "flex-end", justifyContent: "center",
        }} onClick={onClose}>
            <div
                style={{
                    width: "100%", maxWidth: 720,
                    background: "var(--bg-elevated)",
                    borderRadius: "var(--radius-xl) var(--radius-xl) 0 0",
                    borderTop: "1px solid var(--border-medium)",
                    padding: "var(--space-6)",
                    maxHeight: "85vh", overflow: "auto",
                }}
                onClick={e => e.stopPropagation()}
            >
                <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-5)" }}>
                    <h2 style={{ fontSize: 16, fontWeight: 600 }}>Upload Submissions</h2>
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}><X size={15} /></button>
                </div>

                {/* Mode switch */}
                <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-5)", borderBottom: "1px solid var(--border)", paddingBottom: "var(--space-3)" }}>
                    <button className={`btn btn-sm ${uploadMode === "batch" ? "btn-primary" : "btn-ghost"}`}
                        onClick={() => setUploadMode("batch")}>
                        <Users size={12} /> Batch Upload
                    </button>
                    <button className={`btn btn-sm ${uploadMode === "single" ? "btn-primary" : "btn-ghost"}`}
                        onClick={() => setUploadMode("single")}>
                        <Plus size={12} /> Single Student
                    </button>
                </div>

                {/* Shared: assignment selector */}
                <div className="input-group" style={{ marginBottom: "var(--space-4)" }}>
                    <label className="input-label">Assignment</label>
                    <select className="input" value={selectedAssignment} onChange={e => {
                        setSelectedAssignment(e.target.value);
                        setFiles([]); setSingleFile(null); setProgresses({});
                        setRoster([]);
                        setSingleStudentId("");
                        setSingleStudentName("");
                    }}>
                        <option value="">Choose assignment…</option>
                        {assignments.map(a => (
                            <option key={a.id} value={a.id}>
                                {a.title}{a.has_code_question ? " 🖥 [Coding]" : ""}
                            </option>
                        ))}
                    </select>
                    {isCodingAssignment && (
                        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-2)", padding: "var(--space-2) var(--space-3)", background: "var(--accent-dim)", borderRadius: "var(--radius)", fontSize: 12, color: "var(--accent)" }}>
                            <Code2 size={13} /> Coding assignment — upload student code files (.py, .java, .cpp, etc.)
                        </div>
                    )}
                </div>

                {uploadMode === "batch" && (
                    <div className="flex flex-col gap-4">
                        <div className="flex items-center gap-2">
                            <button
                                className={`btn btn-sm ${rosterMode === "classroom" ? "btn-primary" : "btn-ghost"}`}
                                onClick={() => {
                                    setRosterMode("classroom");
                                    const mapped = (classroomStudents ?? []).map(s => ({
                                        student_id: s.userId,
                                        student_name: s.fullName || s.userId,
                                    }));
                                    setRoster(mapped);
                                }}
                            >
                                Classroom Roster
                            </button>
                            <button
                                className={`btn btn-sm ${rosterMode === "csv" ? "btn-primary" : "btn-ghost"}`}
                                onClick={() => setRosterMode("csv")}
                            >
                                CSV Roster
                            </button>
                            {rosterMode === "classroom" && (
                                <button
                                    className="btn btn-secondary btn-sm"
                                    onClick={async () => {
                                        const res = await refetchClassroomStudents();
                                        const mapped = (res.data ?? []).map(s => ({
                                            student_id: s.userId,
                                            student_name: s.fullName || s.userId,
                                        }));
                                        setRoster(mapped);
                                        toast("success", "Classroom roster pulled", `${mapped.length} students`);
                                    }}
                                    disabled={!hasClassroomCourse || rosterLoading}
                                >
                                    {rosterLoading ? <><RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} /> Pulling…</> : "Pull Students"}
                                </button>
                            )}
                        </div>
                        {/* Roster CSV */}
                        {rosterMode === "csv" ? (
                            <div className="input-group">
                                <label className="input-label">Student Roster (CSV)</label>
                                <div
                                    style={{
                                        border: "2px dashed var(--border-medium)", borderRadius: "var(--radius-lg)",
                                        padding: "var(--space-5)", textAlign: "center", cursor: "pointer",
                                        background: roster.length > 0 ? "var(--success-dim)" : "var(--bg-elevated)",
                                        transition: "all 0.15s",
                                    }}
                                    onClick={() => {
                                        const input = document.createElement("input");
                                        input.type = "file"; input.accept = ".csv";
                                        input.onchange = e => {
                                            const f = (e.target as HTMLInputElement).files?.[0];
                                            if (f) handleRosterFile(f);
                                        };
                                        input.click();
                                    }}
                                >
                                    {roster.length > 0 ? (
                                        <div className="flex items-center justify-center gap-2" style={{ color: "var(--success)" }}>
                                            <CheckCircle size={16} /> {roster.length} students loaded
                                        </div>
                                    ) : (
                                        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                                            <Users size={20} style={{ margin: "0 auto var(--space-2)", opacity: 0.4 }} />
                                            Drop CSV or click — columns: <code style={{ fontFamily: "var(--font-mono)" }}>student_id,student_name</code>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "var(--space-2) var(--space-3)", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)" }}>
                                {hasClassroomCourse
                                    ? `Using Classroom course ${classroomCourseId}. Match by file name = Classroom userId or normalized full name.`
                                    : "Selected assignment does not have a valid Classroom numeric course id yet."}
                            </div>
                        )}

                        {/* Files */}
                        <div className="input-group">
                            <label className="input-label">Submission Files</label>
                            <div
                                style={{
                                    border: "2px dashed var(--border-medium)", borderRadius: "var(--radius-lg)",
                                    padding: "var(--space-5)", textAlign: "center", cursor: "pointer",
                                    background: files.length > 0 ? "var(--accent-dim)" : "var(--bg-elevated)",
                                }}
                                onClick={() => fileInputRef.current?.click()}
                                onDragOver={e => e.preventDefault()}
                                onDrop={e => { e.preventDefault(); setFiles(Array.from(e.dataTransfer.files)); }}
                            >
                                <input ref={fileInputRef} type="file" multiple accept={fileAccept}
                                    style={{ display: "none" }}
                                    onChange={e => setFiles(Array.from(e.target.files ?? []))} />
                                {files.length > 0 ? (
                                    <div style={{ color: "var(--accent)", fontSize: 13 }}>
                                        <FileText size={16} style={{ margin: "0 auto var(--space-2)" }} />
                                        {files.length} files selected
                                    </div>
                                ) : (
                                    <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                                        <Upload size={20} style={{ margin: "0 auto var(--space-2)", opacity: 0.4 }} />
                                        {fileHint}
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* File list with match status */}
                        {files.length > 0 && (
                            <div style={{ maxHeight: 200, overflow: "auto" }}>
                                {files.map(f => {
                                    const match = matchFile(f);
                                    const prog = progresses[f.name];
                                    const ext = f.name.split(".").pop() ?? "";
                                    return (
                                        <div key={f.name} style={{
                                            display: "flex", alignItems: "center", gap: "var(--space-3)",
                                            padding: "var(--space-2) var(--space-3)",
                                            borderRadius: "var(--radius-sm)",
                                            background: prog === "done" ? "var(--success-dim)" : prog === "error" ? "var(--danger-dim)" : "var(--bg-elevated)",
                                            marginBottom: 4,
                                        }}>
                                            {prog === "done" ? <CheckCircle size={13} style={{ color: "var(--success)", flexShrink: 0 }} />
                                                : prog === "error" ? <XCircle size={13} style={{ color: "var(--danger)", flexShrink: 0 }} />
                                                    : prog === "uploading" ? <RefreshCw size={13} style={{ color: "var(--accent)", animation: "spin 1s linear infinite", flexShrink: 0 }} />
                                                        : match ? <CheckCircle size={13} style={{ color: "var(--success)", flexShrink: 0 }} />
                                                            : <AlertTriangle size={13} style={{ color: "var(--warning)", flexShrink: 0 }} />}
                                            {isCodingAssignment && <span style={{ fontSize: 10, fontWeight: 700, color: "var(--accent)", background: "var(--accent-dim)", padding: "1px 5px", borderRadius: 3, flexShrink: 0 }}>.{ext}</span>}
                                            <span className="font-mono text-xs truncate" style={{ flex: 1 }}>{f.name}</span>
                                            <span style={{ fontSize: 11, color: "var(--text-muted)", flexShrink: 0 }}>
                                                {match ? match.student_name || match.student_id : roster.length ? "No match" : (rosterMode === "classroom" ? "Pull students" : "Load roster")}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        <button className="btn btn-primary btn-lg" onClick={uploadAll}
                            disabled={!selectedAssignment || files.length === 0}>
                            <Upload size={14} /> Upload {files.length > 0 ? `${files.length} Files` : "Files"}
                        </button>
                    </div>
                )}

                {uploadMode === "single" && (
                    <div className="flex flex-col gap-4">
                        <div className="flex items-center gap-2">
                            <button
                                className={`btn btn-sm ${rosterMode === "classroom" ? "btn-primary" : "btn-ghost"}`}
                                onClick={async () => {
                                    setRosterMode("classroom");
                                    const res = await refetchClassroomStudents();
                                    const mapped = (res.data ?? []).map(s => ({
                                        student_id: s.userId,
                                        student_name: s.fullName || s.userId,
                                    }));
                                    setRoster(mapped);
                                }}
                                disabled={!hasClassroomCourse}
                            >
                                Classroom Mode
                            </button>
                            <button
                                className={`btn btn-sm ${rosterMode === "csv" ? "btn-primary" : "btn-ghost"}`}
                                onClick={() => setRosterMode("csv")}
                            >
                                Manual Mode
                            </button>
                        </div>
                        {rosterMode === "classroom" && roster.length > 0 && (
                            <div className="input-group">
                                <label className="input-label">Select Student From Classroom</label>
                                <select
                                    className="input"
                                    value={singleStudentId}
                                    onChange={e => {
                                        const id = e.target.value;
                                        setSingleStudentId(id);
                                        const found = roster.find(r => r.student_id === id);
                                        setSingleStudentName(found?.student_name || "");
                                    }}
                                >
                                    <option value="">Choose student…</option>
                                    {roster.map(s => (
                                        <option key={s.student_id} value={s.student_id}>
                                            {s.student_name} ({s.student_id})
                                        </option>
                                    ))}
                                </select>
                            </div>
                        )}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                            <div className="input-group">
                                <label className="input-label">Student ID *</label>
                                <input className="input" placeholder="e.g. 21CS001"
                                    value={singleStudentId} onChange={e => setSingleStudentId(e.target.value)} />
                            </div>
                            <div className="input-group">
                                <label className="input-label">Student Name</label>
                                <input className="input" placeholder="Full name (optional)"
                                    value={singleStudentName} onChange={e => setSingleStudentName(e.target.value)} />
                            </div>
                        </div>

                        <div className="input-group">
                            <label className="input-label">
                                {isCodingAssignment ? "Code File *" : "Submission File *"}
                            </label>
                            <div
                                style={{
                                    border: "2px dashed var(--border-medium)", borderRadius: "var(--radius-lg)",
                                    padding: "var(--space-5)", textAlign: "center", cursor: "pointer",
                                    background: singleFile ? "var(--accent-dim)" : "var(--bg-elevated)",
                                }}
                                onClick={() => singleFileRef.current?.click()}
                                onDragOver={e => e.preventDefault()}
                                onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setSingleFile(f); }}
                            >
                                <input ref={singleFileRef} type="file" accept={fileAccept}
                                    style={{ display: "none" }}
                                    onChange={e => { const f = e.target.files?.[0]; if (f) setSingleFile(f); }} />
                                {singleFile ? (
                                    <div style={{ color: "var(--accent)", fontSize: 13 }}>
                                        <FileText size={16} style={{ margin: "0 auto var(--space-2)" }} />
                                        {singleFile.name}
                                        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                                            {(singleFile.size / 1024).toFixed(1)} KB
                                        </div>
                                    </div>
                                ) : (
                                    <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                                        <Upload size={20} style={{ margin: "0 auto var(--space-2)", opacity: 0.4 }} />
                                        {isCodingAssignment
                                            ? "Drop a code file (.py, .java, .cpp, .zip) or click"
                                            : "Drop a PDF or image, or click to browse"}
                                    </div>
                                )}
                            </div>
                        </div>

                        <button className="btn btn-primary btn-lg" onClick={uploadSingle}
                            disabled={!selectedAssignment || !singleStudentId.trim() || !singleFile || singleUploading}>
                            {singleUploading
                                ? <><RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} /> Uploading…</>
                                : <><Upload size={14} /> Upload Submission</>}
                        </button>
                    </div>
                )}
            </div>
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
    );
}

// ── Main page ──────────────────────────────────────────────────────────────

function SubmissionsPageInner() {
    const searchParams = useSearchParams();
    const router = useRouter();
    const { toast } = useToast();
    const qc = useQueryClient();

    const preselectedAssignmentId = searchParams.get("assignmentId");

    const [selectedAssignmentId, setSelectedAssignmentId] = useState(preselectedAssignmentId ?? "");
    const [search, setSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState<SubmissionStatus | "">("");
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [showUpload, setShowUpload] = useState(false);
    const [releaseConfirm, setReleaseConfirm] = useState(false);
    const [deleteConfirm, setDeleteConfirm] = useState(false);

    const { data: assignments = [] } = useQuery({
        queryKey: ["assignments"],
        queryFn: api.assignments.list,
    });

    const { data: submissions = [], isLoading } = useQuery({
        queryKey: ["submissions", selectedAssignmentId, statusFilter],
        queryFn: () => selectedAssignmentId
            ? api.submissions.listByAssignment(selectedAssignmentId, statusFilter || undefined)
            : Promise.resolve([]),
        enabled: !!selectedAssignmentId,
        refetchInterval: (q) => {
            const data = q.state.data as Submission[] | undefined;
            const hasActive = data?.some(s => ["pending", "processing", "ocr_done", "grading"].includes(s.status));
            return hasActive ? 3000 : false;
        },
    });

    const selectedAssignment = assignments.find(a => a.id === selectedAssignmentId);

    const filtered = submissions.filter(s => {
        const q = search.toLowerCase();
        return (!q || s.student_id.toLowerCase().includes(q) || (s.student_name ?? "").toLowerCase().includes(q));
    });

    const toggleSelect = (id: string) => {
        setSelected(prev => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    };

    const selectAll = () => {
        setSelected(filtered.every(s => selected.has(s.id))
            ? new Set()
            : new Set(filtered.map(s => s.id))
        );
    };

    const releaseMutation = useMutation({
        mutationFn: () => api.grades.release([...selected]),
        onSuccess: r => {
            toast("success", `${(r.released as string[]).length} grades released!`);
            qc.invalidateQueries({ queryKey: ["submissions"] });
            setSelected(new Set());
            setReleaseConfirm(false);
        },
        onError: (e: Error) => toast("error", "Release failed", e.message),
    });

    const draftMutation = useMutation({
        mutationFn: () => api.grades.pushDraft([...selected]),
        onSuccess: r => {
            toast("success", `Draft pushed for ${(r.synced_as_draft as string[]).length} submissions`);
            qc.invalidateQueries({ queryKey: ["submissions"] });
            setSelected(new Set());
        },
        onError: (e: Error) => toast("error", "Push failed", e.message),
    });

    const deleteMutation = useMutation({
        mutationFn: () => api.submissions.bulkDelete([...selected]),
        onSuccess: r => {
            toast("success", `Deleted ${(r.deleted as string[]).length} submissions`);
            qc.invalidateQueries({ queryKey: ["submissions"] });
            setSelected(new Set());
            setDeleteConfirm(false);
        },
        onError: (e: Error) => toast("error", "Delete failed", e.message),
    });

    const gradedSubmissions = submissions.filter(s => s.status === "graded");
    const failedSubmissions = submissions.filter(s => s.status === "failed");
    const pendingSubmissions = submissions.filter(s => ["pending", "processing", "ocr_done", "grading"].includes(s.status));

    const updateAssignmentSelection = (nextAssignmentId: string) => {
        setSelectedAssignmentId(nextAssignmentId);
        setSelected(new Set());

        const params = new URLSearchParams(searchParams.toString());
        if (nextAssignmentId) {
            params.set("assignmentId", nextAssignmentId);
        } else {
            params.delete("assignmentId");
        }
        const nextQuery = params.toString();
        router.replace(nextQuery ? `/submissions?${nextQuery}` : "/submissions", { scroll: false });
    };

    return (
        <PageShell sidebar={<Sidebar items={SIDEBAR_ITEMS} />}>
            {/* Header */}
            <div className="page-header">
                <div>
                    <h1 className="page-title">Submissions</h1>
                    <p className="page-subtitle">
                        {selectedAssignment
                            ? `${selectedAssignment.title} · ${submissions.length} total`
                            : "Select an assignment to view submissions"}
                    </p>
                </div>
                <div className="page-actions">
                    <button className="btn btn-secondary" onClick={() => setShowUpload(true)}>
                        <Upload size={14} /> Upload
                    </button>
                    {selectedAssignmentId && (
                        <a
                            className="btn btn-secondary"
                            href={api.assignments.gradesCSVUrl(selectedAssignmentId)}
                            target="_blank" rel="noreferrer"
                        >
                            <Download size={14} /> CSV
                        </a>
                    )}
                </div>
            </div>

            {/* Assignment picker */}
            <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-4)" }}>
                <select
                    className="input"
                    style={{ maxWidth: 320 }}
                    value={selectedAssignmentId}
                    onChange={e => updateAssignmentSelection(e.target.value)}
                >
                    <option value="">Select assignment…</option>
                    {assignments.map(a => <option key={a.id} value={a.id}>{a.title}</option>)}
                </select>

                {selectedAssignmentId && (
                    <>
                        <div style={{ position: "relative" }}>
                            <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
                            <input
                                className="input" style={{ paddingLeft: 32, width: 200 }}
                                placeholder="Search students…"
                                value={search} onChange={e => setSearch(e.target.value)}
                            />
                        </div>
                        <select
                            className="input" style={{ width: 160 }}
                            value={statusFilter}
                            onChange={e => setStatusFilter(e.target.value as SubmissionStatus | "")}
                        >
                            <option value="">All statuses</option>
                            {(Object.keys(STATUS_LABEL) as SubmissionStatus[]).map(s => (
                                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                            ))}
                        </select>
                    </>
                )}
            </div>

            {/* Stats strip */}
            {selectedAssignmentId && submissions.length > 0 && (
                <div className="stat-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "var(--space-4)" }}>
                    {[
                        { label: "Total", value: submissions.length, variant: "default" },
                        { label: "Graded", value: gradedSubmissions.length, variant: "success" },
                        { label: "Pending", value: pendingSubmissions.length, variant: "warning" },
                        { label: "Failed", value: failedSubmissions.length, variant: "danger" },
                    ].map(({ label, value, variant }) => (
                        <div key={label} className={`stat-card ${variant}`} style={{ padding: "var(--space-4)" }}>
                            <div className="stat-label">{label}</div>
                            <div className="stat-value" style={{ fontSize: 22 }}>{value}</div>
                        </div>
                    ))}
                </div>
            )}

            {/* Bulk actions */}
            {selected.size > 0 && (
                <div style={{
                    display: "flex", alignItems: "center", gap: "var(--space-3)",
                    padding: "var(--space-3) var(--space-4)",
                    background: "var(--accent-dim)", borderRadius: "var(--radius-lg)",
                    border: "1px solid rgba(59,130,246,0.25)",
                    marginBottom: "var(--space-4)",
                }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>{selected.size} selected</span>
                    <button className="btn btn-secondary btn-sm" onClick={() => draftMutation.mutate()} disabled={draftMutation.isPending}>
                        <Send size={12} /> Push Draft
                    </button>
                    <button className="btn btn-success btn-sm" onClick={() => setReleaseConfirm(true)}>
                        <Globe size={12} /> Release Grades
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>
                        <X size={12} /> Clear
                    </button>
                    <button className="btn btn-danger btn-sm" onClick={() => setDeleteConfirm(true)}>
                        <Trash2 size={12} /> Delete
                    </button>
                </div>
            )}

            {/* Table */}
            {!selectedAssignmentId ? (
                <div className="empty-state">
                    <FileText size={48} className="empty-icon" />
                    <div className="empty-title">Select an assignment</div>
                    <div className="empty-message">Choose an assignment from the dropdown above to view its submissions.</div>
                </div>
            ) : isLoading ? (
                <div className="flex flex-col gap-3">
                    {[...Array(5)].map((_, i) => <div key={i} className="skeleton" style={{ height: 52, borderRadius: "var(--radius)" }} />)}
                </div>
            ) : filtered.length === 0 ? (
                <div className="empty-state">
                    <Upload size={40} className="empty-icon" />
                    <div className="empty-title">No submissions yet</div>
                    <div className="empty-message">Upload student PDFs or pull from Google Classroom.</div>
                    <button className="btn btn-primary" onClick={() => setShowUpload(true)}>
                        <Upload size={13} /> Upload Now
                    </button>
                </div>
            ) : (
                <div className="card" style={{ padding: 0 }}>
                    <div className="table-wrap">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th style={{ width: 40 }}>
                                        <input type="checkbox" checked={filtered.every(s => selected.has(s.id))} onChange={selectAll} />
                                    </th>
                                    <th>Student</th>
                                    <th>Status</th>
                                    <th>Updated</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {filtered.map(sub => (
                                    <tr
                                        key={sub.id}
                                        className="clickable"
                                        onClick={() => router.push(`/submissions/${sub.id}${selectedAssignmentId ? `?assignmentId=${selectedAssignmentId}` : ""}`)}
                                    >
                                        <td onClick={e => { e.stopPropagation(); toggleSelect(sub.id); }}>
                                            <input type="checkbox" checked={selected.has(sub.id)} onChange={() => toggleSelect(sub.id)} />
                                        </td>
                                        <td>
                                            <div className="font-medium" style={{ color: "var(--text-primary)" }}>{sub.student_id}</div>
                                            {sub.student_name && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{sub.student_name}</div>}
                                        </td>
                                        <td>
                                            <span className={`badge ${STATUS_CLASS[sub.status]}`}>
                                                {STATUS_LABEL[sub.status]}
                                            </span>
                                        </td>
                                        <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                            {new Date(sub.updated_at).toLocaleString()}
                                        </td>
                                        <td>
                                            <ChevronRight size={14} style={{ color: "var(--text-muted)" }} />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Upload panel */}
            {showUpload && (
                <UploadPanel
                    assignments={assignments}
                    initialAssignmentId={selectedAssignmentId}
                    onClose={() => setShowUpload(false)}
                />
            )}

            {/* Release confirm */}
            <ConfirmModal
                open={releaseConfirm}
                variant="warning"
                title="Release Grades to Students"
                message={`You're about to release grades for ${selected.size} submissions to Google Classroom. Students will be notified immediately. This cannot be undone.`}
                confirmText="Release Grades"
                onConfirm={() => releaseMutation.mutate()}
                onCancel={() => setReleaseConfirm(false)}
                loading={releaseMutation.isPending}
            />
            <ConfirmModal
                open={deleteConfirm}
                variant="danger"
                title="Delete Selected Submissions"
                message={`Delete ${selected.size} submissions permanently? Grades and audit history for them will also be deleted.`}
                confirmText="Delete Submissions"
                onConfirm={() => deleteMutation.mutate()}
                onCancel={() => setDeleteConfirm(false)}
                loading={deleteMutation.isPending}
            />

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </PageShell>
    );
}

// Globe icon inline since we use it
function Globe({ size = 16 }: { size?: number }) {
    return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>;
}

export default function SubmissionsPage() {
    return (
        <Suspense fallback={<div style={{ padding: "var(--space-8)", color: "var(--text-muted)", textAlign: "center" }}>Loading…</div>}>
            <SubmissionsPageInner />
        </Suspense>
    );
}
