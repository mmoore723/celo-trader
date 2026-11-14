/**
 * AuthContext.tsx — Authentication state provider for the entire app.
 *
 * On first load, checks /api/auth/me with the session cookie.
 * If valid → sets user + isAuthenticated = true.
 * If 401  → isAuthenticated = false → App.tsx shows Login page.
 *
 * Also exposed: logout() which calls /api/auth/logout and clears state.
 */
/* oxlint-disable react/only-export-components -- provider and its colocated hook are one authentication boundary */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export interface AuthUser {
  support_session?: {actor_name:string;target_name:string;expires_at:number;expired?:boolean};
  email:          string;
  name:           string;
  user_id?:       string;
  is_admin?:      boolean;
  access_profile?: string;
  terms_accepted?: boolean;   // true = user accepted the current ToS version
}

interface AuthState {
  isAuthenticated: boolean;
  user: AuthUser | null;
  loading: boolean;                    // true while the /me check is in-flight
  login: (user: AuthUser) => void;
  logout: () => Promise<void>;
  acceptTerms: () => Promise<void>;    // call after user clicks "I Agree"
}

const AuthContext = createContext<AuthState>({
  isAuthenticated: false,
  user: null,
  loading: true,
  login:        () => {},
  logout:       async () => {},
  acceptTerms:  async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]       = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const changed = (event: StorageEvent) => { if (event.key === 'celo-account-switch') window.location.reload(); };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []);

  useEffect(() => {
    if (!user?.user_id) return;
    const nativeFetch=window.fetch;
    const expectedUser=user.user_id;
    window.fetch=(input,init)=>{
      const url=new URL(input instanceof Request?input.url:String(input),window.location.href);
      if(url.origin!==window.location.origin || !url.pathname.startsWith('/api/')) return nativeFetch(input,init);
      const headers=new Headers(input instanceof Request?input.headers:undefined);
      new Headers(init?.headers).forEach((value,key)=>headers.set(key,value));
      headers.set('X-Celo-Account-User',expectedUser);
      return nativeFetch(input,{...init,headers});
    };
    return ()=>{window.fetch=nativeFetch;};
  },[user?.user_id]);

  // ── Check session on mount ─────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/auth/me", { credentials: "include" });
        if (r.ok) {
          const data = await r.json();
          setUser({
            support_session: data.support_session,
            email:          data.username || data.email || "user",
            name:           data.username || data.name  || data.email || "user",
            user_id:        data.user_id,
            is_admin:       !!data.is_admin,
            access_profile: data.access_profile ?? "legacy",
            terms_accepted: !!data.terms_accepted,
          });
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

  // Called when user clicks "I Agree" on the Terms page.
  // POSTs acceptance to the backend, then marks the user as having accepted.
  const acceptTerms = async () => {
    const r = await fetch("/api/auth/accept-terms", {
      method: "POST", credentials: "include",
    });
    if (!r.ok) throw new Error("Failed to record acceptance");
    setUser((prev) => prev ? { ...prev, terms_accepted: true } : prev);
  };

  return (
    <AuthContext.Provider
      value={{ isAuthenticated: !!user, user, loading, login, logout, acceptTerms }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
