import { Moon, Sun } from "lucide-react";
import { useThemeStore } from "../../store/theme";

export function ThemeToggle() {
  const { theme, toggle } = useThemeStore();

  return (
    <button
      onClick={toggle}
      className="btn btn-ghost btn-sm"
      title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
      aria-label="Toggle theme"
    >
      {theme === "light" ? (
        <Moon size={15} className="text-ink-muted" />
      ) : (
        <Sun size={15} className="text-ink-muted" />
      )}
    </button>
  );
}
