"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";
import type { Grade, OCRBlock, AuditLog } from "@/lib/api";
import { SourceBadge, SyncBadge, TriageDot } from "./StatusBadge";

interface Props {
  grade: Grade | null;
  blocks: OCRBlock[];
  auditLog: AuditLog[];
  maxMarks: number;
  selectedBlockIndex: number | null;
  onSelectBlock: (i: number) => void;
  onEditBlock: (index: number, newContent: string, reason: string) => void;
  onReleaseDraft: () => void;
  onReleaseAssigned: () => void;
  releasing: boolean;
}

type Tab = "ocr" | "grade" | "audit";

export default function GradePanel({
  grade, blocks, auditLog, maxMarks,
  selectedBlockIndex, onSelectBlock, onEditBlock,
  onReleaseDraft, onReleaseAssigned, releasing,
}: Props) {
  const [tab, setTab] = useState<Tab>("ocr");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editText, setEditText]         = useState("");
  const [editReason, setEditReason]     = useState("");

  const pct = grade ? Math.round((grade.total_score / maxMarks) * 100) : null;

  function startEdit(b: OCRBlock) {
    setEditingIndex(b.index);
    setEditText(b.content);
    setEditReason("");
  }
  function commitEdit() {
    if (editingIndex === null) return;
    onEditBlock(editingIndex, editText, editReason);
    setEditingIndex(null);
  }

  return (
    <div className="flex flex-col h-full glass overflow-hidden">
      {/* Score header */}
      <div className="p-4 border-b border-white/[0.06]">
        {grade ? (
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold gradient-text">{grade.total_score}</span>
                <span className="text-slate-400 text-sm">/ {maxMarks}</span>
                <span className="text-slate-500 text-xs">({pct}%)</span>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <SourceBadge source={grade.source} />
                <SyncBadge status={grade.classroom_status} />
                {grade.is_truncated && (
                  <span className="pill bg-amber-900/60 text-amber-300">⚠ Truncated</span>
                )}
              </div>
            </div>
            {/* Score ring */}
            <div className="relative h-14 w-14 flex-shrink-0">
              <svg className="h-14 w-14 -rotate-90" viewBox="0 0 56 56">
                <circle cx="28" cy="28" r="22" fill="none" stroke="#1e2436" strokeWidth="6" />
                <circle
                  cx="28" cy="28" r="22" fill="none"
                  stroke={pct! >= 70 ? "#22c55e" : pct! >= 40 ? "#f59e0b" : "#ef4444"}
                  strokeWidth="6"
                  strokeDasharray={`${(pct! / 100) * 138.2} 138.2`}
                  strokeLinecap="round"
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-slate-300">
                {pct}%
              </span>
            </div>
          </div>
        ) : (
          <div className="text-slate-500 text-sm py-1">No grade yet — OCR may still be processing.</div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/[0.06] text-xs font-medium">
        {(["ocr", "grade", "audit"] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              "flex-1 py-2.5 capitalize transition-colors",
              tab === t
                ? "text-accent-light border-b-2 border-accent"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            {t === "ocr" ? `OCR Blocks (${blocks.length})` : t === "grade" ? "Breakdown" : "Audit Log"}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        <AnimatePresence mode="wait">
          {tab === "ocr" && (
            <motion.div key="ocr" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-1.5">
              {blocks.length === 0 && <p className="text-slate-500 text-xs text-center py-8">No OCR blocks detected.</p>}
              {blocks.map((b, i) => (
                <motion.div
                  key={i}
                  whileHover={{ x: 2 }}
                  onClick={() => onSelectBlock(i)}
                  className={clsx(
                    "p-2.5 rounded-xl border cursor-pointer transition-all",
                    selectedBlockIndex === i
                      ? "border-accent/60 bg-accent/10"
                      : "border-white/[0.05] bg-surface-2/60 hover:border-white/[0.12]"
                  )}
                >
                  {editingIndex === i ? (
                    <div className="space-y-2" onClick={e => e.stopPropagation()}>
                      <textarea
                        className="w-full text-xs bg-surface-3 rounded-lg p-2 text-slate-100 border border-white/10 resize-none focus:outline-none focus:border-accent"
                        rows={3}
                        value={editText}
                        onChange={e => setEditText(e.target.value)}
                      />
                      <input
                        className="w-full text-xs bg-surface-3 rounded-lg p-2 text-slate-400 border border-white/10 focus:outline-none focus:border-accent"
                        placeholder="Reason for correction (optional)"
                        value={editReason}
                        onChange={e => setEditReason(e.target.value)}
                      />
                      <div className="flex gap-2">
                        <button onClick={commitEdit} className="flex-1 py-1 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-dark transition-colors">Save & Re-grade</button>
                        <button onClick={() => setEditingIndex(null)} className="flex-1 py-1 rounded-lg bg-surface-3 text-slate-400 text-xs hover:text-slate-200 transition-colors">Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-2">
                      <TriageDot confidence={b.confidence} flagged={b.flagged} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">{b.label}{b.question ? ` · ${b.question}` : ""}</span>
                          <span className="text-[10px] text-slate-600">{(b.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <p className="text-xs text-slate-200 leading-relaxed line-clamp-3">{b.content || <span className="italic text-slate-500">empty</span>}</p>
                      </div>
                      <button
                        onClick={e => { e.stopPropagation(); startEdit(b); }}
                        className="text-[10px] text-slate-500 hover:text-accent-light transition-colors flex-shrink-0 mt-0.5"
                        title="Edit OCR text"
                      >
                        ✏
                      </button>
                    </div>
                  )}
                </motion.div>
              ))}
            </motion.div>
          )}

          {tab === "grade" && (
            <motion.div key="grade" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-2">
              {!grade && <p className="text-slate-500 text-xs text-center py-8">No grade available yet.</p>}
              {grade && Object.entries(grade.breakdown_json).map(([qId, q]) => (
                <div key={qId} className="p-3 rounded-xl bg-surface-2/60 border border-white/[0.05] space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-300">{qId}</span>
                    <span className={clsx("text-sm font-bold", q.marks_awarded >= q.max_marks * 0.7 ? "text-success" : q.marks_awarded >= q.max_marks * 0.4 ? "text-warning" : "text-danger")}>
                      {q.marks_awarded} <span className="text-slate-500 font-normal text-xs">/ {q.max_marks}</span>
                    </span>
                  </div>
                  {q.is_truncated && <span className="pill bg-amber-900/40 text-amber-400 text-[10px]">⚠ Answer truncated</span>}
                  <p className="text-xs text-slate-400 leading-relaxed">{q.feedback}</p>
                  {/* Mini progress bar */}
                  <div className="h-1 rounded-full bg-surface-3">
                    <div
                      className={clsx("h-1 rounded-full transition-all", q.marks_awarded >= q.max_marks * 0.7 ? "bg-success" : q.marks_awarded >= q.max_marks * 0.4 ? "bg-warning" : "bg-danger")}
                      style={{ width: `${(q.marks_awarded / q.max_marks) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </motion.div>
          )}

          {tab === "audit" && (
            <motion.div key="audit" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-2">
              {auditLog.length === 0 && <p className="text-slate-500 text-xs text-center py-8">No audit entries yet.</p>}
              {auditLog.map(log => (
                <div key={log.id} className="p-2.5 rounded-xl bg-surface-2/60 border border-white/[0.05]">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-semibold text-accent-light capitalize">{log.action.replace(/_/g, " ")}</span>
                    <span className="text-[10px] text-slate-600">{new Date(log.timestamp).toLocaleString()}</span>
                  </div>
                  <p className="text-[10px] text-slate-500">by <span className="text-slate-400">{log.changed_by}</span>{log.reason ? ` — ${log.reason}` : ""}</p>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Release buttons */}
      {grade && (
        <div className="p-3 border-t border-white/[0.06] flex gap-2">
          <button
            onClick={onReleaseDraft}
            disabled={releasing || grade.classroom_status === "released"}
            className="flex-1 py-2 rounded-xl text-xs font-semibold bg-surface-3 text-slate-300 hover:bg-surface-3/80 disabled:opacity-40 transition-all"
          >
            Push Draft
          </button>
          <button
            onClick={onReleaseAssigned}
            disabled={releasing || grade.classroom_status === "released"}
            className="flex-1 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-accent to-indigo-500 text-white hover:opacity-90 disabled:opacity-40 transition-all shadow-md shadow-accent/20"
          >
            {releasing ? "Releasing…" : "Release Grade"}
          </button>
        </div>
      )}
    </div>
  );
}
