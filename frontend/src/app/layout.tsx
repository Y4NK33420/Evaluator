import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AMGS — Automated Marksheet Grading System",
  description: "AI-assisted grading pipeline for university exam papers",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-surface">
        <nav className="sticky top-0 z-50 border-b border-white/[0.06] bg-surface-1/80 backdrop-blur-md">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex h-14 items-center justify-between">
              <a href="/" className="flex items-center gap-2.5 group">
                <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-accent to-indigo-400 flex items-center justify-center text-white text-xs font-bold shadow-md shadow-accent/30">
                  A
                </div>
                <span className="font-semibold text-sm tracking-wide gradient-text">AMGS</span>
              </a>
              <div className="flex items-center gap-1 text-xs text-slate-400">
                <span className="h-2 w-2 rounded-full bg-success animate-pulse-slow inline-block" />
                System Online
              </div>
            </div>
          </div>
        </nav>
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
