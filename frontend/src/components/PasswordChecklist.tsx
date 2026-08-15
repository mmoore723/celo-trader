/**
 * PasswordChecklist.tsx — Live password complexity indicator.
 *
 * Renders a 5-row checklist; each row turns green as the user satisfies
 * the requirement. Import isPasswordValid() to gate your submit button.
 *
 * Usage:
 *   import { PasswordChecklist, isPasswordValid } from "../components/PasswordChecklist";
 *   <PasswordChecklist password={pw} />
 *   <button disabled={!isPasswordValid(pw)}>Submit</button>
 */
/* oxlint-disable react/only-export-components -- validation must stay identical to the rendered checklist */
import type { CSSProperties } from "react";

// ── Shared validation logic (mirrors auth/users.py validate_password) ─────────
const SPECIAL_RE  = /[!@#$%^&*()\-_=+[\]{}|;:,.<>?/~`'"]/;

export interface PasswordRule {
  label: string;
  test:  (pw: string) => boolean;
}

export const PASSWORD_RULES: PasswordRule[] = [
  { label: "At least 12 characters",        test: (pw) => pw.length >= 12 },
  { label: "One uppercase letter (A–Z)",     test: (pw) => /[A-Z]/.test(pw) },
  { label: "One lowercase letter (a–z)",     test: (pw) => /[a-z]/.test(pw) },
  { label: "One number (0–9)",               test: (pw) => /\d/.test(pw) },
  { label: "One special character (!@#$…)",  test: (pw) => SPECIAL_RE.test(pw) },
];

/** Returns true only when ALL requirements are satisfied. */
export function isPasswordValid(pw: string): boolean {
  return PASSWORD_RULES.every((r) => r.test(pw));
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  password: string;
  /** Show rules even when password is empty (default: only show after first keystroke) */
  alwaysShow?: boolean;
  style?: CSSProperties;
}

export function PasswordChecklist({ password, alwaysShow = false, style }: Props) {
  // Hide entirely until the user starts typing (unless alwaysShow)
  if (!alwaysShow && password.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, ...style }}>
      {PASSWORD_RULES.map((rule) => {
        const met = rule.test(password);
        return (
          <div
            key={rule.label}
            style={{
              display:    "flex",
              alignItems: "center",
              gap:        6,
              fontSize:   11,
              color:      met ? "#00c853" : password.length > 0 ? "#f87171" : "#64748b",
              transition: "color 0.15s",
            }}
          >
            {/* Icon */}
            <span style={{
              display:        "inline-flex",
              alignItems:     "center",
              justifyContent: "center",
              width:          14,
              height:         14,
              borderRadius:   "50%",
              background:     met
                ? "rgba(0,200,83,0.15)"
                : password.length > 0 ? "rgba(248,113,113,0.12)" : "rgba(100,116,139,0.1)",
              fontSize:       9,
              fontWeight:     700,
              flexShrink:     0,
              transition:     "background 0.15s",
            }}>
              {met ? "✓" : "✕"}
            </span>
            {rule.label}
          </div>
        );
      })}
    </div>
  );
}
