"use client";
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import {
    Plus, Search, Filter, BookOpen, Code2, FileText,
    Calendar, ChevronRight, MoreHorizontal, Trash2, Edit3, X,
} from "lucide-react";
import { PageShell, Sidebar } from "@/components/layout/Shell";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Assignment } from "@/lib/types";

const SIDEBAR_ITEMS = [
    { href: "/assignments", label: "All Assignments", icon: BookOpen },
    { href: "/assignments/new", label: "Create New", icon: Plus },
];

function AssignmentTypeIcon({ has_code, type }: { has_code: boolean; type: string }) {
    if (has_code) return <Code2 size={14} style={{ color: "var(--accent)" }} />;
    if (type === "objective") return <FileText size={14} style={{ color: "var(--info)" }} />;
    return <FileText size={14} style={{ color: "var(--text-muted)" }} />;
}

function AssignmentCard({
    assignment,
    onDelete,
}: { assignment: Assignment; onDelete: (id: string) => void }) {
    const router = useRouter();
    const [menuOpen, setMenuOpen] = useState(false);
    const isOverdue = assignment.deadline && !assignment.is_published && new Date(assignment.deadline) < new Date();

    return (
        <motion.div
            className="spotlight-card"
            style={{ padding: "var(--space-5)", cursor: "pointer", position: "relative" }}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
            onMouseMove={e => {
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                (e.currentTarget as HTMLDivElement).style.setProperty("--mouse-x", `${e.clientX - rect.left}px`);
                (e.currentTarget as HTMLDivElement).style.setProperty("--mouse-y", `${e.clientY - rect.top}px`);
            }}
            onClick={() => router.push(`/assignments/${assignment.id}`)}
        >
            {/* Top row */}
            <div className="flex items-center justify-between" style={{ marginBottom: "var(--space-3)" }}>
                <div className="flex items-center gap-2">
                    <AssignmentTypeIcon has_code={assignment.has_code_question} type={assignment.question_type} />
                    <span className={`badge ${assignment.is_published ? "badge-success" : "badge-default"}`}>
                        {assignment.is_published ? "Published" : "Draft"}
                    </span>
                    {isOverdue && <span className="badge badge-danger">Overdue</span>}
                </div>
                <div style={{ position: "relative" }} onClick={e => e.stopPropagation()}>
                    <button
                        className="btn btn-ghost btn-icon btn-sm"
                        onClick={() => setMenuOpen(!menuOpen)}
                    >
                        <MoreHorizontal size={14} />
                    </button>
                    <AnimatePresence>
                        {menuOpen && (
                            <motion.div
                                className="dropdown"
                                initial={{ opacity: 0, scale: 0.95, y: -4 }}
                                animate={{ opacity: 1, scale: 1, y: 0 }}
                                exit={{ opacity: 0, scale: 0.95 }}
                                transition={{ duration: 0.12 }}
                            >
                                <button className="dropdown-item" onClick={() => router.push(`/assignments/${assignment.id}`)}>
                                    <Edit3 size={13} /> Edit / View
                                </button>
                                <div className="dropdown-divider" />
                                <button className="dropdown-item danger" onClick={() => { setMenuOpen(false); onDelete(assignment.id); }}>
                                    <Trash2 size={13} /> Delete
                                </button>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </div>

            {/* Title */}
            <div className="font-semibold truncate" style={{ color: "var(--text-primary)", fontSize: 14, marginBottom: 4 }}>
                {assignment.title}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: "var(--space-4)" }}>
                {assignment.has_code_question ? "Coding" : assignment.question_type.charAt(0).toUpperCase() + assignment.question_type.slice(1)}
                {" · "}{assignment.max_marks} marks
                {" · "}<span style={{ fontFamily: "var(--font-mono)" }}>{assignment.course_id}</span>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1" style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    <Calendar size={11} />
                    {assignment.deadline
                        ? new Date(assignment.deadline).toLocaleDateString()
                        : "No deadline"}
                </div>
                <div className="flex items-center gap-1" style={{ fontSize: 12, color: "var(--accent)" }}>
                    Open <ChevronRight size={13} />
                </div>
            </div>
        </motion.div>
    );
}

export default function AssignmentsPage() {
    const { courseId } = useAuth();
    const router = useRouter();
    const qc = useQueryClient();
    const { toast } = useToast();

    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState<"all" | "draft" | "published">("all");
    const [deleteId, setDeleteId] = useState<string | null>(null);

    const { data: assignments = [], isLoading } = useQuery({
        queryKey: ["assignments"],
        queryFn: api.assignments.list,
    });

    const deleteMutation = useMutation({
        mutationFn: (id: string) => api.assignments.remove(id),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["assignments"] });
            toast("success", "Assignment deleted");
            setDeleteId(null);
        },
        onError: (err: Error) => toast("error", "Delete failed", err.message),
    });

    const filtered = assignments.filter(a => {
        const matchSearch = a.title.toLowerCase().includes(search.toLowerCase())
            || a.course_id.toLowerCase().includes(search.toLowerCase());
        const matchFilter = filter === "all"
            || (filter === "published" && a.is_published)
            || (filter === "draft" && !a.is_published);
        return matchSearch && matchFilter;
    });

    const deleteTarget = assignments.find(a => a.id === deleteId);

    return (
        <PageShell sidebar={<Sidebar items={SIDEBAR_ITEMS} />}>
            {/* Page header */}
            <div className="page-header">
                <div>
                    <h1 className="page-title">Assignments</h1>
                    <p className="page-subtitle">
                        {assignments.length} total · {assignments.filter(a => a.is_published).length} published
                    </p>
                </div>
                <div className="page-actions">
                    <button
                        className="btn btn-primary"
                        onClick={() => router.push("/assignments/new")}
                    >
                        <Plus size={15} /> New Assignment
                    </button>
                </div>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-3" style={{ marginBottom: "var(--space-6)" }}>
                <div style={{ position: "relative", flex: 1, maxWidth: 340 }}>
                    <Search size={14} style={{
                        position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
                        color: "var(--text-muted)", pointerEvents: "none",
                    }} />
                    <input
                        className="input"
                        style={{ paddingLeft: 36 }}
                        placeholder="Search assignments…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                    />
                    {search && (
                        <button className="btn btn-ghost btn-icon btn-sm" style={{
                            position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)",
                        }} onClick={() => setSearch("")}>
                            <X size={13} />
                        </button>
                    )}
                </div>

                <div className="flex items-center gap-1" style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: 3,
                }}>
                    {(["all", "draft", "published"] as const).map(f => (
                        <button
                            key={f}
                            className="btn btn-sm"
                            style={{
                                background: filter === f ? "var(--bg-hover)" : "transparent",
                                color: filter === f ? "var(--text-primary)" : "var(--text-muted)",
                                border: "none",
                            }}
                            onClick={() => setFilter(f)}
                        >
                            {f.charAt(0).toUpperCase() + f.slice(1)}
                        </button>
                    ))}
                </div>

                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {filtered.length} shown
                </div>
            </div>

            {/* Grid */}
            {isLoading ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "var(--space-4)" }}>
                    {[...Array(6)].map((_, i) => (
                        <div key={i} className="skeleton" style={{ height: 168, borderRadius: "var(--radius-lg)" }} />
                    ))}
                </div>
            ) : filtered.length === 0 ? (
                <div className="empty-state">
                    <BookOpen size={48} className="empty-icon" />
                    <div className="empty-title">
                        {search ? "No assignments match your search" : "No assignments yet"}
                    </div>
                    <div className="empty-message">
                        {search
                            ? "Try a different search term or clear the filter."
                            : "Create your first assignment to start grading."}
                    </div>
                    {!search && (
                        <button className="btn btn-primary" onClick={() => router.push("/assignments/new")}>
                            <Plus size={14} /> Create Assignment
                        </button>
                    )}
                </div>
            ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "var(--space-4)" }}>
                    {filtered.map(a => (
                        <AssignmentCard key={a.id} assignment={a} onDelete={setDeleteId} />
                    ))}
                </div>
            )}

            {/* Delete confirm */}
            <ConfirmModal
                open={!!deleteId}
                variant="danger"
                title="Delete Assignment"
                message={
                    <>
                        Are you sure you want to delete{" "}
                        <strong style={{ color: "var(--text-primary)" }}>{deleteTarget?.title}</strong>?
                        This will also delete all submissions and grades. This action cannot be undone.
                    </>
                }
                confirmText="Delete Assignment"
                onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
                onCancel={() => setDeleteId(null)}
                loading={deleteMutation.isPending}
            />
        </PageShell>
    );
}
