"use client";
import React, { createContext, useContext, useCallback, useState } from "react";
import type { Toast, ToastVariant } from "@/lib/types";
import { motion, AnimatePresence } from "motion/react";
import { CheckCircle, XCircle, AlertTriangle, Info, X } from "lucide-react";

interface ToastContextValue {
    toast: (variant: ToastVariant, title: string, message?: string) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => { } });
export const useToast = () => useContext(ToastContext);

const ICONS = {
    success: <CheckCircle size={16} style={{ color: "var(--success)", flexShrink: 0 }} />,
    error: <XCircle size={16} style={{ color: "var(--danger)", flexShrink: 0 }} />,
    warning: <AlertTriangle size={16} style={{ color: "var(--warning)", flexShrink: 0 }} />,
    info: <Info size={16} style={{ color: "var(--info)", flexShrink: 0 }} />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const toast = useCallback((variant: ToastVariant, title: string, message?: string) => {
        const id = Math.random().toString(36).slice(2);
        setToasts(prev => [...prev, { id, variant, title, message }]);
        setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4500);
    }, []);

    const remove = (id: string) => setToasts(prev => prev.filter(t => t.id !== id));

    return (
        <ToastContext.Provider value={{ toast }}>
            {children}
            <div className="toast-container">
                <AnimatePresence>
                    {toasts.map(t => (
                        <motion.div
                            key={t.id}
                            className={`toast toast-${t.variant}`}
                            initial={{ opacity: 0, y: 20, scale: 0.95 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, x: 60, scale: 0.95 }}
                            transition={{ duration: 0.2 }}
                        >
                            {ICONS[t.variant]}
                            <div className="toast-body">
                                <div className="toast-title">{t.title}</div>
                                {t.message && <div className="toast-message">{t.message}</div>}
                            </div>
                            <button
                                className="btn btn-ghost btn-icon btn-sm"
                                onClick={() => remove(t.id)}
                                style={{ flexShrink: 0 }}
                            >
                                <X size={13} />
                            </button>
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>
        </ToastContext.Provider>
    );
}
