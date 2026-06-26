/**
 * AuthContext.tsx — Authentication state provider for the entire app.
 *
 * On first load, checks /api/auth/me with the session cookie.
 * If valid → sets user + isAuthenticated = true.
 * If 401  → isAuthenticated = false → App.tsx shows Login page.
 *
 * Also exposed: logout() which calls /api/auth/logout and clears state.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export interface AuthUser {
  email: string;
  name: string;
}

interface AuthState {
  isAuthenticated: boolean;
  user: AuthUser | null;
  loading: boolean;             // true while the /me check is in-flight
  login: (user: AuthUser) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  isAuthenticated: false,
  user: null,
  loading: true,
  login: () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]       = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // ── Check session on mount ─────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include" });
        if (r.ok) {
          const data = await r.json();
          setUser({ email: data.email, name: data.name || data.email });
        }
        // 401 → user stays null → redirect to login
      } catch {
        // Network error → treat as unauthenticated
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // ── Handle mid-session 401s from any API call ──────────────────────────────
  // api.ts dispatches "celo:session-expired" whenever a protected route returns
  // 401. This catches the case where the session expires AFTER the initial
  // /api/auth/me check passes (e.g. tab left open overnight).
  useEffect(() => {
    const handler = () => {
      setUser(null);
      // Best-effort cookie clear; the real clear happens on the next login.
      fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
    };
    window.addEventListener("celo:session-expired", handler);
    return () => window.removeEventListener("celo:session-expired", handler);
  }, []);

  const login = (u: AuthUser) => setUser(u);

  const logout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } finally {
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{ isAuthenticated: !!user, user, loading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
