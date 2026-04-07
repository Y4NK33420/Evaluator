import type { SubmissionStatus, GradeSource, ClassroomStatus } from "@/lib/api";
import { clsx } from "clsx";

// ── Status Badge ─────────────────────────────────────────────────────────────

const STATUS_MAP: Record<SubmissionStatus, { label: string; color: string; dot: string }> = {
  pending:    { label: "Pending",    color: "bg-slate-700/60 text-slate-300",   dot: "bg-slate-400" },
  processing: { label: "Processing", color: "bg-blue-900/60  text-blue-300",    dot: "bg-blue-400 animate-pulse" },
  ocr_done:   { label: "OCR Done",   color: "bg-indigo-900/60 text-indigo-300", dot: "bg-indigo-400" },
  grading:    { label: "Grading",    color: "bg-violet-900/60 text-violet-300", dot: "bg-violet-400 animate-pulse" },
  graded:     { label: "Graded",     color: "bg-emerald-900/60 text-emerald-300", dot: "bg-emerald-400" },
  failed:     { label: "Failed",     color: "bg-red-900/60  text-red-300",      dot: "bg-red-400" },
};

export function StatusBadge({ status }: { status: SubmissionStatus }) {
  const s = STATUS_MAP[status] ?? STATUS_MAP.failed;
  return (
    <span className={clsx("pill", s.color)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

// ── Classroom sync badge ──────────────────────────────────────────────────────

const SYNC_MAP: Record<ClassroomStatus, { label: string; color: string }> = {
  not_synced: { label: "Not Synced", color: "bg-slate-700/60 text-slate-400" },
  draft:      { label: "Draft",      color: "bg-amber-900/60 text-amber-300" },
  released:   { label: "Released",   color: "bg-emerald-900/60 text-emerald-300" },
};

export function SyncBadge({ status }: { status: ClassroomStatus }) {
  const s = SYNC_MAP[status] ?? SYNC_MAP.not_synced;
  return <span className={clsx("pill", s.color)}>{s.label}</span>;
}

// ── Grade source badge ────────────────────────────────────────────────────────

const SOURCE_MAP: Record<GradeSource, { label: string; color: string }> = {
  AI_Generated: { label: "AI",         color: "bg-violet-900/60 text-violet-300" },
  AI_Corrected: { label: "AI (Edited)", color: "bg-indigo-900/60 text-indigo-300" },
  AI_HEALED:    { label: "AI Healed",  color: "bg-sky-900/60 text-sky-300" },
  TA_Manual:    { label: "Manual",     color: "bg-amber-900/60 text-amber-300" },
};

export function SourceBadge({ source }: { source: GradeSource }) {
  const s = SOURCE_MAP[source] ?? SOURCE_MAP.AI_Generated;
  return <span className={clsx("pill", s.color)}>{s.label}</span>;
}

// ── Triage dot (confidence) ───────────────────────────────────────────────────

export function TriageDot({ confidence, flagged }: { confidence: number; flagged: boolean }) {
  const color = flagged
    ? "bg-amber-400"
    : confidence >= 0.9
    ? "bg-emerald-400"
    : "bg-yellow-400";
  return (
    <span
      className={clsx("inline-block h-2 w-2 rounded-full flex-shrink-0", color)}
      title={`Confidence: ${(confidence * 100).toFixed(0)}%`}
    />
  );
}
