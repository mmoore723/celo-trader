/**
 * Tooltip.tsx — Hover tooltip for jargon labels across the app.
 *
 * Usage:
 *   import { Tooltip } from "../components/Tooltip";
 *   <Tooltip text="Relative Volume: ...">RVOL</Tooltip>
 *
 * Renders a dotted underline on the wrapped text; on hover shows a
 * dark card tooltip positioned above via fixed coords (never clipped
 * by overflow:hidden containers).
 */
import { useState, useRef } from "react";

interface Props {
  text: string;              // Plain-text definition shown on hover
  children: React.ReactNode; // The label text to annotate
  width?: number;            // Max tooltip width in px (default 230)
}

export function Tooltip({ text, children, width = 230 }: Props) {
  const [show, setShow]   = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const ref = useRef<HTMLSpanElement>(null);

  function handleEnter() {
    if (ref.current) {
      const r = ref.current.getBoundingClientRect();
      // Position below the label, centered horizontally
      setCoords({ top: r.bottom + 6, left: r.left + r.width / 2 });
    }
    setShow(true);
  }

  return (
    <span
      ref={ref}
      onMouseEnter={handleEnter}
      onMouseLeave={() => setShow(false)}
      style={{ cursor: "help", borderBottom: "1px dotted var(--ink-faint)", display: "inline" }}
    >
      {children}

      {show && (
        <span
          role="tooltip"
          style={{
            position:    "fixed",
            top:         coords.top,
            left:        coords.left,
            transform:   "translateX(-50%)",
            zIndex:      9999,
            maxWidth:    width,
            width:       "max-content",
            background:  "var(--surface)",
            border:      "1px solid var(--border)",
            borderRadius: 8,
            padding:     "7px 11px",
            fontSize:    11,
            lineHeight:  1.55,
            color:       "var(--ink-muted)",
            boxShadow:   "0 6px 20px rgba(0,0,0,0.35)",
            pointerEvents: "none",
            whiteSpace:  "normal",
            textTransform: "none",
            fontWeight:  400,
            letterSpacing: 0,
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
