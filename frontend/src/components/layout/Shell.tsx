"use client";
import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
    LayoutDashboard, BookOpen, FileText, Code2, Settings,
    GraduationCap, ChevronRight,
} from "lucide-react";
import { useAuth } from "@/lib/auth";

const NAV_LINKS = [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/assignments", label: "Assignments", icon: BookOpen },
    { href: "/submissions", label: "Submissions", icon: FileText },
    { href: "/code-eval", label: "Code Eval", icon: Code2 },
];

export function TopNav() {
    const pathname = usePathname();
    const { actor } = useAuth();
    const initials = actor
        ? actor.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2)
        : "??";

    return (
        <nav className="topnav">
            <Link href="/dashboard" className="topnav-brand">
                <div className="topnav-logo">
                    <GraduationCap size={16} />
                </div>
                <span className="topnav-name">AMGS</span>
            </Link>

            <div className="topnav-links">
                {NAV_LINKS.map(({ href, label, icon: Icon }) => {
                    const active = pathname.startsWith(href);
                    return (
                        <Link key={href} href={href} className={`topnav-link ${active ? "active" : ""}`}>
                            <Icon size={15} />
                            {label}
                        </Link>
                    );
                })}
            </div>

            <div className="topnav-right">
                <Link href="/settings" className="btn btn-ghost btn-icon btn-sm">
                    <Settings size={15} />
                </Link>
                <Link href="/settings" title={actor ?? "Profile"}>
                    <div className="topnav-avatar">{initials}</div>
                </Link>
            </div>
        </nav>
    );
}

// ── Section sidebar ────────────────────────────────────────────────────────

interface SidebarItem {
    href: string;
    label: string;
    icon: React.ComponentType<{ size?: number; className?: string }>;
    badge?: number | string;
}

interface SidebarProps {
    items: SidebarItem[];
    header?: React.ReactNode;
}

export function Sidebar({ items, header }: SidebarProps) {
    const pathname = usePathname();
    return (
        <aside className="page-sidebar">
            {header && <div style={{ marginBottom: "var(--space-4)" }}>{header}</div>}
            {items.map(({ href, label, icon: Icon, badge }) => {
                const active = pathname === href || (href !== "/" && pathname.startsWith(href + "/"));
                return (
                    <Link key={href} href={href} className={`sidebar-link ${active ? "active" : ""}`}>
                        <Icon size={15} className="sidebar-link-icon" />
                        <span style={{ flex: 1 }}>{label}</span>
                        {badge !== undefined && (
                            <span className={`badge ${active ? "badge-accent" : "badge-default"}`}
                                style={{ fontSize: 10, padding: "1px 6px" }}>
                                {badge}
                            </span>
                        )}
                        {active && <ChevronRight size={13} style={{ opacity: 0.4 }} />}
                    </Link>
                );
            })}
        </aside>
    );
}

// ── Page shell ────────────────────────────────────────────────────────────

interface PageShellProps {
    sidebar?: React.ReactNode;
    children: React.ReactNode;
}

export function PageShell({ sidebar, children }: PageShellProps) {
    return (
        <div className="page-shell">
            <TopNav />
            {sidebar}
            <main className={`page-content ${!sidebar ? "no-sidebar" : ""}`}>
                {children}
            </main>
        </div>
    );
}
