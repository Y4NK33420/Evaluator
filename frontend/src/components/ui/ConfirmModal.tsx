"use client";
import React from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, AlertTriangle } from "lucide-react";

interface ConfirmModalProps {
    open: boolean;
    title: string;
    message: React.ReactNode;
    confirmText?: string;
    cancelText?: string;
    variant?: "danger" | "warning" | "default";
    onConfirm: () => void;
    onCancel: () => void;
    loading?: boolean;
}

export function ConfirmModal({
    open, title, message, confirmText = "Confirm", cancelText = "Cancel",
    variant = "default", onConfirm, onCancel, loading,
}: ConfirmModalProps) {
    return (
        <AnimatePresence>
            {open && (
                <motion.div
                    className="modal-overlay"
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    onClick={onCancel}
                >
                    <motion.div
                        className="modal"
                        initial={{ opacity: 0, scale: 0.94, y: 12 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.94, y: 12 }}
                        transition={{ duration: 0.18 }}
                        onClick={e => e.stopPropagation()}
                    >
                        <div className="modal-header">
                            <div className="flex items-center gap-3">
                                {variant !== "default" && (
                                    <div style={{
                                        width: 36, height: 36, borderRadius: "var(--radius)",
                                        background: variant === "danger" ? "var(--danger-dim)" : "var(--warning-dim)",
                                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                                    }}>
                                        <AlertTriangle size={17} style={{ color: variant === "danger" ? "var(--danger)" : "var(--warning)" }} />
                                    </div>
                                )}
                                <span className="modal-title">{title}</span>
                            </div>
                            <button className="btn btn-ghost btn-icon btn-sm" onClick={onCancel}>
                                <X size={15} />
                            </button>
                        </div>

                        <div className="modal-body">{message}</div>

                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={onCancel} disabled={loading}>
                                {cancelText}
                            </button>
                            <button
                                className={`btn ${variant === "danger" ? "btn-danger" : variant === "warning" ? "btn-secondary" : "btn-primary"}`}
                                onClick={onConfirm}
                                disabled={loading}
                            >
                                {loading ? "Working…" : confirmText}
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}
