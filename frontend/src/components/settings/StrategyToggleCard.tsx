import type { ReactNode } from "react";

export function Toggle({
  label, checked, onChange, disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return <div className={`flex items-center justify-between gap-3 py-2 ${disabled ? "opacity-60" : ""}`}>
    <span className="text-sm" style={{ color: "var(--ink)" }}>{label}</span>
    <button
      type="button"
      className={`toggle-track ${checked ? "on" : ""}`}
      onClick={() => { if (!disabled) onChange(!checked); }}
      role="switch"
      aria-checked={checked}
      aria-disabled={disabled}
      disabled={disabled}
      aria-label={label}
    >
      <div className="toggle-thumb" />
    </button>
  </div>;
}

export function StrategyToggleCard({
  label, checked, onChange, disabled = false, children, separated = false,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  children: ReactNode;
  separated?: boolean;
}) {
  return <div
    className={`px-1 py-1 ${separated ? "mt-2" : ""}`}
    style={{ borderBottom: "1px solid var(--border)" }}
  >
    <Toggle label={label} checked={checked} onChange={onChange} disabled={disabled} />
    {children}
  </div>;
}
