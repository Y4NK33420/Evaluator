"use client";
import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface AuthState {
    actor: string | null;
    courseId: string | null;
    login: (actor: string, courseId: string) => void;
    logout: () => void;
}

const AuthContext = createContext<AuthState>({
    actor: null, courseId: null, login: () => { }, logout: () => { },
});

export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [actor, setActor] = useState<string | null>(null);
    const [courseId, setCourseId] = useState<string | null>(null);
    const router = useRouter();

    useEffect(() => {
        const a = localStorage.getItem("amgs_actor");
        const c = localStorage.getItem("amgs_course_id");
        if (a) { setActor(a); setCourseId(c); }
    }, []);

    const login = (actor: string, courseId: string) => {
        localStorage.setItem("amgs_actor", actor);
        localStorage.setItem("amgs_course_id", courseId);
        setActor(actor);
        setCourseId(courseId);
        router.push("/dashboard");
    };

    const logout = () => {
        localStorage.removeItem("amgs_actor");
        localStorage.removeItem("amgs_course_id");
        setActor(null);
        setCourseId(null);
        router.push("/login");
    };

    return (
        <AuthContext.Provider value={{ actor, courseId, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
}
