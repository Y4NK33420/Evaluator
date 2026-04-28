"use client";
import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import {
    GraduationCap, Eye, EyeOff, CheckCircle, AlertCircle,
    WifiOff, Link2Off, RefreshCw, Zap, ChevronDown, ChevronUp,
    ExternalLink, FileKey,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type ClassroomCheckState =
    | { phase: "idle" }
    | { phase: "checking" }
    | { phase: "backend_offline"; url: string }
    | {
        phase: "connected";
        expired: boolean;
        has_refresh: boolean;
        scopes: string[];
        missing_scopes: string[];
        has_required_scopes: boolean;
        ready: boolean;
    }
    | { phase: "token_missing"; credentials_ok: boolean }
    | { phase: "token_invalid"; reason: string }
    | { phase: "generating" }
    | { phase: "generate_error"; message: string };

// ── Status banner ──────────────────────────────────────────────────────────────

function ClassroomBanner({
    state,
    onCheck,
    onGenerate,
    onForceGenerate,
}: {
    state: ClassroomCheckState;
    onCheck: () => void;
    onGenerate: () => void;
    onForceGenerate: () => void;
}) {
    const [showScopes, setShowScopes] = useState(false);

    const bannerStyle = (variant: "success" | "warning" | "danger" | "offline" | "neutral"): React.CSSProperties => ({
        display: "flex",
        alignItems: "flex-start",
        gap: "var(--space-3)",
        padding: "var(--space-3) var(--space-4)",
        borderRadius: "var(--radius)",
        marginBottom: "var(--space-6)",
        background:
            variant === "success" ? "var(--success-dim)"
                : variant === "warning" ? "var(--warning-dim)"
                    : variant === "danger" ? "var(--danger-dim)"
                        : variant === "offline" ? "rgba(99,102,241,0.1)"
                            : "var(--bg-elevated)",
        border: `1px solid ${variant === "success" ? "rgba(34,197,94,0.25)"
            : variant === "warning" ? "rgba(245,158,11,0.3)"
                : variant === "danger" ? "rgba(239,68,68,0.3)"
                    : variant === "offline" ? "rgba(99,102,241,0.25)"
                        : "var(--border)"
            }`,
    });

    if (state.phase === "idle" || state.phase === "checking") {
        return (
            <div style={bannerStyle("neutral")}>
                <div className="skeleton" style={{ width: 16, height: 16, borderRadius: "50%", flexShrink: 0, marginTop: 2 }} />
                <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                    {state.phase === "idle" ? "Connecting to backend…" : "Checking Google Classroom…"}
                </span>
            </div>
        );
    }

    if (state.phase === "backend_offline") {
        return (
            <div style={bannerStyle("offline")}>
                <WifiOff size={16} style={{ color: "#6366F1", flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#A5B4FC" }}>Backend Offline</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, lineHeight: 1.5 }}>
                        Cannot reach <code style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>{state.url}</code>.
                        Start the backend server, then refresh.
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, fontFamily: "var(--font-mono)", background: "rgba(0,0,0,0.2)", borderRadius: "var(--radius-sm)", padding: "3px 8px", display: "inline-block" }}>
                        cd backend &amp;&amp; uvicorn app.main:app --reload --port 8080
                    </div>
                </div>
                <button
                    className="btn btn-ghost btn-sm"
                    onClick={onCheck}
                    style={{ fontSize: 11, flexShrink: 0 }}
                >
                    <RefreshCw size={11} /> Retry
                </button>
            </div>
        );
    }

    if (state.phase === "connected") {
        const isFullyOk = state.ready || ((!state.expired || state.has_refresh) && state.has_required_scopes);
        return (
            <div style={bannerStyle(isFullyOk ? "success" : "warning")}>
                <CheckCircle size={16} style={{ color: isFullyOk ? "var(--success)" : "var(--warning)", flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: isFullyOk ? "var(--success)" : "var(--warning)" }}>
                        Google Classroom Connected
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                        {state.expired && !state.has_refresh
                            ? "Token expired — no refresh token. Click Generate Token to re-authorise."
                            : state.expired
                                ? "Token expired but will auto-refresh on first use."
                                : "OAuth credentials valid."}
                    </div>
                    {!state.has_required_scopes && (
                        <div style={{ fontSize: 11, color: "var(--warning)", marginTop: 2 }}>
                            Missing required scopes: {state.missing_scopes.length}
                        </div>
                    )}
                    {state.scopes.length > 0 && (
                        <button
                            onClick={() => setShowScopes(s => !s)}
                            style={{ fontSize: 10, color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 4, display: "flex", alignItems: "center", gap: 3 }}
                        >
                            {showScopes ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                            {state.scopes.length} scopes granted
                        </button>
                    )}
                    {showScopes && (
                        <div style={{ marginTop: 4, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)", lineHeight: 1.8 }}>
                            {state.scopes.map(s => <div key={s}>{s.replace("https://www.googleapis.com/auth/", "…/")}</div>)}
                        </div>
                    )}
                </div>
                <div className="flex items-center gap-2" style={{ marginLeft: "auto" }}>
                    <button className="btn btn-ghost btn-sm" onClick={onGenerate} style={{ fontSize: 11, flexShrink: 0 }}>
                        <Zap size={11} /> Reconnect
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={onForceGenerate} style={{ fontSize: 11, flexShrink: 0 }}>
                        <RefreshCw size={11} /> Force Re-auth
                    </button>
                </div>
            </div>
        );
    }

    if (state.phase === "token_missing") {
        return (
            <div style={bannerStyle("warning")}>
                <FileKey size={16} style={{ color: "var(--warning)", flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--warning)" }}>
                        Google Token Not Found
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, lineHeight: 1.5 }}>
                        {state.credentials_ok
                            ? "credentials.json is present. Click Generate Token to open the browser OAuth flow."
                            : "Neither token.json nor credentials.json found. Download credentials.json from GCP Console first."}
                    </div>
                    {!state.credentials_ok && (
                        <a
                            href="https://console.cloud.google.com/apis/credentials"
                            target="_blank"
                            rel="noreferrer"
                            style={{ fontSize: 10, color: "var(--accent)", marginTop: 4, display: "inline-flex", alignItems: "center", gap: 3 }}
                        >
                            <ExternalLink size={10} /> Open GCP Console
                        </a>
                    )}
                </div>
                {state.credentials_ok && (
                    <button className="btn btn-ghost btn-sm" onClick={onForceGenerate} style={{ fontSize: 11, flexShrink: 0, color: "var(--warning)" }}>
                        <Zap size={11} /> Generate Token
                    </button>
                )}
            </div>
        );
    }

    if (state.phase === "generating") {
        return (
            <div style={bannerStyle("neutral")}>
                <RefreshCw size={16} style={{ color: "var(--accent)", animation: "spin 1.2s linear infinite", flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>Starting OAuth…</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                        If a browser does not open automatically, check backend logs for the Google auth URL and open it manually.
                        Then complete sign-in and return here.
                    </div>
                </div>
            </div>
        );
    }

    if (state.phase === "generate_error") {
        return (
            <div style={bannerStyle("danger")}>
                <AlertCircle size={16} style={{ color: "var(--danger)", flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--danger)" }}>Token Generation Failed</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, lineHeight: 1.5, wordBreak: "break-word" }}>
                        {state.message}
                    </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={onForceGenerate} style={{ fontSize: 11, flexShrink: 0 }}>
                    <RefreshCw size={11} /> Retry
                </button>
            </div>
        );
    }

    // token_invalid
    if (state.phase === "token_invalid") {
        return (
            <div style={bannerStyle("danger")}>
                <Link2Off size={16} style={{ color: "var(--danger)", flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--danger)" }}>Token Invalid</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, wordBreak: "break-word" }}>
                        {state.reason}
                    </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={onForceGenerate} style={{ fontSize: 11, flexShrink: 0 }}>
                    <Zap size={11} /> Regenerate
                </button>
            </div>
        );
    }

    return null;
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LoginPage() {
    const { actor, login } = useAuth();
    const router = useRouter();

    const [name, setName] = useState("");
    const [courseId, setCourseId] = useState("");
    const [showId, setShowId] = useState(false);
    const [error, setError] = useState("");
    const [checkState, setCheckState] = useState<ClassroomCheckState>({ phase: "idle" });

    const API_URL = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

    useEffect(() => {
        if (actor) router.replace("/dashboard");
    }, [actor, router]);

    const checkStatus = async () => {
        setCheckState({ phase: "checking" });
        try {
            const s = await api.classroom.authStatus();
            if (s.authenticated) {
                setCheckState({
                    phase: "connected",
                    expired: Boolean(s.expired),
                    has_refresh: Boolean(s.has_refresh_token),
                    scopes: s.scopes ?? [],
                    missing_scopes: s.missing_scopes ?? [],
                    has_required_scopes: Boolean(s.has_required_scopes),
                    ready: Boolean(s.ready),
                });
            } else {
                const reason = s.reason ?? "";
                if (reason === "token_missing") {
                    setCheckState({
                        phase: "token_missing",
                        credentials_ok: Boolean(s.credentials_file_exists),
                    });
                } else {
                    setCheckState({ phase: "token_invalid", reason });
                }
            }
        } catch (err) {
            // Distinguish network/CORS errors (backend offline) from app errors
            if (err instanceof ApiError) {
                setCheckState({ phase: "token_invalid", reason: err.message });
            } else {
                // fetch itself failed → backend is not reachable
                setCheckState({ phase: "backend_offline", url: API_URL });
            }
        }
    };

    const generateToken = async (forceReauth = false) => {
        setCheckState({ phase: "generating" });
        try {
            const s = await api.classroom.generateToken(forceReauth);
            if (s.authenticated) {
                setCheckState({
                    phase: "connected",
                    expired: Boolean(s.expired),
                    has_refresh: Boolean(s.has_refresh_token),
                    scopes: s.scopes ?? [],
                    missing_scopes: s.missing_scopes ?? [],
                    has_required_scopes: Boolean(s.has_required_scopes),
                    ready: Boolean(s.ready),
                });
            } else {
                setCheckState({
                    phase: "generate_error",
                    message: s.reason ?? "Unknown error from backend.",
                });
            }
        } catch (err) {
            const msg = err instanceof ApiError
                ? err.message
                : err instanceof TypeError
                    ? "Backend not reachable."
                    : String(err);
            setCheckState({ phase: "generate_error", message: msg });
        }
    };

    useEffect(() => {
        checkStatus();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim()) { setError("Please enter your name"); return; }
        if (!courseId.trim()) { setError("Please enter a Course ID"); return; }
        login(name.trim(), courseId.trim());
    };

    return (
        <div className="login-page">
            {/* Background glows */}
            <div className="login-bg-glow" style={{ background: "#3B82F6", top: "20%", left: "15%" }} />
            <div className="login-bg-glow" style={{ background: "#6366F1", bottom: "20%", right: "15%" }} />

            <motion.div
                className="login-card"
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }}
            >
                {/* Logo */}
                <div className="flex flex-col items-center gap-3" style={{ marginBottom: "var(--space-8)" }}>
                    <div style={{
                        width: 52, height: 52, borderRadius: "var(--radius-md)",
                        background: "linear-gradient(135deg, var(--accent) 0%, #6366F1 100%)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        boxShadow: "0 8px 24px var(--accent-glow)",
                    }}>
                        <GraduationCap size={26} color="#fff" />
                    </div>
                    <div style={{ textAlign: "center" }}>
                        <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                            AMGS
                        </h1>
                        <p className="text-sm" style={{ color: "var(--text-muted)", marginTop: 2 }}>
                            Automated Marksheet Grading System
                        </p>
                    </div>
                </div>

                {/* Classroom status banner */}
                <AnimatePresence mode="wait">
                    <motion.div
                        key={checkState.phase}
                        initial={{ opacity: 0, scale: 0.98 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.97 }}
                        transition={{ duration: 0.15 }}
                    >
                <ClassroomBanner
                    state={checkState}
                    onCheck={checkStatus}
                    onGenerate={() => generateToken(false)}
                    onForceGenerate={() => generateToken(true)}
                />
                    </motion.div>
                </AnimatePresence>

                {/* Form */}
                <form onSubmit={handleSubmit}>
                    <div className="flex flex-col gap-4">
                        <div className="input-group">
                            <label className="input-label" htmlFor="actor-name">Your Name</label>
                            <input
                                id="actor-name"
                                className="input"
                                type="text"
                                placeholder="e.g. Prof. Sharma"
                                value={name}
                                onChange={e => { setName(e.target.value); setError(""); }}
                                autoComplete="name"
                                autoFocus
                            />
                        </div>

                        <div className="input-group">
                            <label className="input-label" htmlFor="course-id">
                                Course ID
                                <span style={{ color: "var(--text-muted)", fontWeight: 400, marginLeft: 4 }}>(for grouping assignments)</span>
                            </label>
                            <div style={{ position: "relative" }}>
                                <input
                                    id="course-id"
                                    className="input"
                                    type={showId ? "text" : "password"}
                                    placeholder="e.g. CS101-2025"
                                    value={courseId}
                                    onChange={e => { setCourseId(e.target.value); setError(""); }}
                                    style={{ paddingRight: 40 }}
                                />
                                <button
                                    type="button"
                                    className="btn btn-ghost btn-icon btn-sm"
                                    onClick={() => setShowId(!showId)}
                                    style={{ position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)" }}
                                >
                                    {showId ? <EyeOff size={14} /> : <Eye size={14} />}
                                </button>
                            </div>
                            <span className="input-hint">This links your assignments together in one workspace.</span>
                        </div>

                        <AnimatePresence>
                            {error && (
                                <motion.div
                                    initial={{ opacity: 0, y: -4 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -4 }}
                                    className="flex items-center gap-2"
                                    style={{ color: "var(--danger)", fontSize: 12 }}
                                >
                                    <AlertCircle size={14} />
                                    {error}
                                </motion.div>
                            )}
                        </AnimatePresence>

                        <button
                            type="submit"
                            className="btn btn-primary btn-lg"
                            style={{ marginTop: "var(--space-2)" }}
                            disabled={checkState.phase === "generating"}
                        >
                            Enter Dashboard
                        </button>

                        {checkState.phase === "backend_offline" && (
                            <div style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "center", lineHeight: 1.5 }}>
                                You can still enter the dashboard — Classroom features will be unavailable until the backend starts.
                            </div>
                        )}
                    </div>
                </form>
            </motion.div>

            <style>{`
                @keyframes spin { to { transform: rotate(360deg); } }
                .login-page {
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: var(--space-6);
                    position: relative;
                    overflow: hidden;
                }
                .login-bg-glow {
                    position: absolute;
                    width: 340px;
                    height: 340px;
                    border-radius: 50%;
                    opacity: 0.08;
                    filter: blur(80px);
                    pointer-events: none;
                }
                .login-card {
                    width: 100%;
                    max-width: 420px;
                    background: var(--bg-surface);
                    border: 1px solid var(--border-medium);
                    border-radius: var(--radius-xl);
                    padding: var(--space-8);
                    box-shadow: var(--shadow-lg);
                    position: relative;
                    z-index: 1;
                }
            `}</style>
        </div>
    );
}
