/**
 * store/theme.ts — Zustand store for light/dark theme.
 * Default: light. Persisted to localStorage.
 */
import { create } from "zustand";

type Theme = "light" | "dark";

interface ThemeState {
  theme: Theme;
  toggle: () => void;
  setTheme: (t: Theme) => void;
}

function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
  localStorage.setItem("celo-theme", t);
}

const saved = localStorage.getItem("celo-theme") as Theme | null;
const initial: Theme = saved ?? "light";   // light is default
applyTheme(initial);

export const useThemeStore = create<ThemeState>((set) => ({
  theme: initial,
  toggle: () =>
    set((s) => {
      const next: Theme = s.theme === "light" ? "dark" : "light";
      applyTheme(next);
      return { theme: next };
    }),
  setTheme: (t) =>
    set(() => {
      applyTheme(t);
      return { theme: t };
    }),
}));
