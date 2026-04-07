"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import type { Submission, Grade, AuditLog, Assignment } from "@/lib/api";
import { api } from "@/lib/api";
import GradePanel from "./GradePanel";

// Canvas must be client-only (no SSR)
const BoundingBoxCanvas = dynamic(() => import("./BoundingBoxCanvas"), { ssr: false });

interface Props {
  submission: Submission;
  assignment: Assignment;
  initialGrade: Grade | null;
  initialAudit: AuditLog[];
}

export default function SplitScreenReview({ submission, assignment, initialGrade, initialAudit }: Props) {
  const [grade, setGrade]           = useState<Grade | null>(initialGrade);
  const [audit, setAudit]           = useState<AuditLog[]>(initialAudit);
  const [blocks, setBlocks]         = useState(submission.ocr_result?.blocks ?? []);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [releasing, setReleasing]   = useState(false);
  const [toast, setToast]           = useState<{ msg: string; ok: boolean } | null>(null);

  const imageUrl = `/api/v1/submissions/image/${submission.id}`;

  function flash(msg: string, ok = true) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  }

  async function handleEditBlock(blockIndex: number, newContent: string, reason: string) {
    try {
      await api.submissions.correctOCR(submission.id, blockIndex, newContent, reason);
      setBlocks(prev => prev.map(b => b.index === blockIndex ? { ...b, content: newContent } : b));
      flash("OCR corrected — re-grading started");
      // Poll for new grade after a delay
      setTimeout(async () => {
        try {
          const g = await api.submissions.grade(submission.id);
          setGrade(g);
          const a = await api.submissions.audit(submission.id);
          setAudit(a);
        } catch { /* grade not ready yet */ }
      }, 8000);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : "Edit failed", false);
    }
  }

  async function handleReleaseDraft() {
    setReleasing(true);
    try {
      await api.grades.releaseDraft([submission.id]);
      const g = await api.submissions.grade(submission.id);
      setGrade(g);
      flash("Draft pushed to Google Classroom");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : "Push failed", false);
    } finally { setReleasing(false); }
  }

  async function handleReleaseAssigned() {
    setReleasing(true);
    try {
      await api.grades.releaseAssigned([submission.id]);
      const g = await api.submissions.grade(submission.id);
      setGrade(g);
      flash("Grade released to students 🎉");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : "Release failed", false);
    } finally { setReleasing(false); }
  }

  return (
    <div className="relative flex flex-col h-[calc(100vh-7rem)] gap-4">
      {/* Toast */}
      {toast && (
        <motion.div
          initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
          className={`fixed top-16 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl text-sm font-medium shadow-xl ${toast.ok ? "bg-emerald-900/90 text-emerald-200 border border-emerald-700/60" : "bg-red-900/90 text-red-200 border border-red-700/60"}`}
        >
          {toast.msg}
        </motion.div>
      )}

      {/* Header strip */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="font-semibold text-slate-100">{submission.student_name ?? submission.student_id}</h1>
          <p className="text-xs text-slate-500 mt-0.5">{assignment.title} · {assignment.max_marks} marks · <span className="capitalize">{assignment.question_type}</span></p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>{blocks.length} blocks</span>
          {(submission.ocr_result?.flagged_count ?? 0) > 0 && (
            <span className="pill bg-amber-900/50 text-amber-300">⚠ {submission.ocr_result!.flagged_count} flagged</span>
          )}
        </div>
      </div>

      {/* Split pane */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* LEFT — scan image with bbox overlay */}
        <div className="flex-1 min-w-0">
          <BoundingBoxCanvas
            imageUrl={imageUrl}
            blocks={blocks}
            selectedIndex={selectedIdx}
            onSelect={setSelectedIdx}
          />
        </div>

        {/* RIGHT — grade panel */}
        <div className="w-[380px] flex-shrink-0 min-h-0">
          <GradePanel
            grade={grade}
            blocks={blocks}
            auditLog={audit}
            maxMarks={assignment.max_marks}
            selectedBlockIndex={selectedIdx}
            onSelectBlock={setSelectedIdx}
            onEditBlock={handleEditBlock}
            onReleaseDraft={handleReleaseDraft}
            onReleaseAssigned={handleReleaseAssigned}
            releasing={releasing}
          />
        </div>
      </div>
    </div>
  );
}
