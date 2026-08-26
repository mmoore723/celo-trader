/**
 * Admin.tsx — User management + Emergency Controls (admin only). Mobile-responsive.
 */
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { UserPlus, Link2, Trash2, RefreshCw, KeyRound, AlertTriangle, CheckCircle2, BrainCircuit } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { PasswordChecklist, isPasswordValid } from "../components/PasswordChecklist";
import { api } from "../lib/api";

interface User {
  user_id:    string;
  username:   string;
  is_admin:   boolean;
  created_at: string;
}

export function Admin() {
  const { user }      = useAuth();
  const [users, setUsers]       = useState<User[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);

  const [newUser, setNewUser]   = useState({ username: "", password: "", is_admin: false });
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  const [resetState, setResetState] = useState<{ uid: string; uname: string; pw: string } | null>(null);
  const [resetMsg,   setResetMsg]   = useState<{ ok: boolean; msg: string } | null>(null);

  const [inviteUrl, setInviteUrl]   = useState<string | null>(null);
  const [inviteExp, setInviteExp]   = useState<number>(48);
  const [inviting, setInviting]     = useState(false);
  const [copied, setCopied]         = useState(false);
  const { data: ranker, isError: rankerError } = useQuery({
    queryKey: ["admin-learning-ranker-status"],
    queryFn: api.learning.rankerStatus,
    refetchInterval: 60_000,
    retry: false,
  });

  // ── Emergency / Maintenance state ─────────────────────────────────────────
  const [maintActive,  setMaintActive]  = useState(false);
  const [maintMessage, setMaintMessage] = useState("");
  const [collectionOnly, setCollectionOnly] = useState(false);
  const [maintWorking, setMaintWorking] = useState(false);
  const [maintResult,  setMaintResult]  = useState<{ ok: boolean; msg: string } | null>(null);

  // Load current maintenance status on mount
  useEffect(() => {
    fetch("/api/admin/maintenance/status", { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) { setMaintActive(d.active); setMaintMessage(d.message || ""); setCollectionOnly(!!d.collection_only); } })
      .catch(() => {});
  }, []);

  async function enableMaintenance() {
    const msg = maintMessage.trim();
    const confirmed = window.confirm(
      "⚠️ HALT ALL TRADING\n\n" +
      "This will:\n" +
      (collectionOnly
        ? "  • Keep existing paper loops scanning for research only\n  • Prevent every entry, exit, cancellation, and broker order\n"
        : "  • Immediately stop every bot loop\n") +
      "  • Show the maintenance screen to all users\n" +
      "  • Block the bot from being started\n\n" +
      "Continue?"
    );
    if (!confirmed) return;
    setMaintWorking(true);
    setMaintResult(null);
    try {
      const r = await fetch("/api/admin/maintenance/enable", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, collection_only: collectionOnly }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed");
      setMaintActive(true);
      setMaintResult({ ok: true, msg: collectionOnly ? "✅ Trading halted. Paper research collection remains on." : "✅ Maintenance active. All bot loops halted." });
    } catch (e: any) {
      setMaintResult({ ok: false, msg: e.message || "Failed to enable maintenance mode" });
    } finally {
      setMaintWorking(false);
    }
  }

  async function disableMaintenance() {
    setMaintWorking(true);
    setMaintResult(null);
    try {
      const r = await fetch("/api/admin/maintenance/disable", {
        method: "POST", credentials: "include",
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed");
      setMaintActive(false);
      setMaintMessage("");
      setMaintResult({ ok: true, msg: "✅ Maintenance cleared. You can now restart the bot." });
    } catch (e: any) {
      setMaintResult({ ok: false, msg: e.message || "Failed to clear maintenance mode" });
    } finally {
      setMaintWorking(false);
    }
  }

  async function loadUsers() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/admin/users", { credentials: "include" });
      if (!r.ok) throw new Error("Unauthorized or server error");
      const d = await r.json();
      setUsers(d.users || []);
    } catch (e: any) {
      setError(e.message || "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadUsers(); }, []);

  async function createUser() {
    if (!newUser.username || !newUser.password) {
      setCreateMsg({ ok: false, msg: "Username and password required" });
      return;
    }
    if (!isPasswordValid(newUser.password)) {
      setCreateMsg({ ok: false, msg: "Password does not meet complexity requirements." });
      return;
    }
    setCreating(true);
    setCreateMsg(null);
    try {
      const r = await fetch("/api/admin/users", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newUser),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Create failed");
      setCreateMsg({ ok: true, msg: `User "${newUser.username}" created.` });
      setNewUser({ username: "", password: "", is_admin: false });
      loadUsers();
    } catch (e: any) {
      setCreateMsg({ ok: false, msg: e.message || "Create failed" });
    } finally {
      setCreating(false);
    }
  }

  async function deleteUser(uid: string, uname: string) {
    if (!confirm(`Delete user "${uname}"? This cannot be undone.`)) return;
    try {
      const r = await fetch(`/api/admin/users/${uid}`, {
        method: "DELETE", credentials: "include"
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Delete failed");
      loadUsers();
    } catch (e: any) {
      alert(e.message || "Delete failed");
    }
  }

  async function resetPassword() {
    if (!resetState || !isPasswordValid(resetState.pw)) {
      setResetMsg({ ok: false, msg: "Password does not meet complexity requirements." });
      return;
    }
    try {
      const r = await fetch(`/api/admin/users/${resetState.uid}/reset-password`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: resetState.pw }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Reset failed");
      setResetMsg({ ok: true, msg: "Password updated!" });
      setTimeout(() => { setResetState(null); setResetMsg(null); }, 1500);
    } catch (e: any) {
      setResetMsg({ ok: false, msg: e.message || "Reset failed" });
    }
  }

  async function generateInvite() {
    setInviting(true);
    setInviteUrl(null);
    try {
      const r = await fetch("/api/admin/invite", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expires_hours: inviteExp }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed");
      setInviteUrl(d.link);
    } catch (e: any) {
      alert(e.message || "Failed to generate invite");
    } finally {
      setInviting(false);
    }
  }

  function copyInvite() {
    if (!inviteUrl) return;
    navigator.clipboard.writeText(inviteUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="p-4 flex flex-col gap-4" style={{ maxWidth: 600, width: "100%" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>
          Admin
        </h2>
        <button className="btn btn-ghost" onClick={loadUsers}>
          <RefreshCw size={13} />
        </button>
      </div>

      {/* The model is intentionally invisible to trading until it has enough
          complete, independent outcomes and passes chronological validation. */}
      <section className="card p-4" aria-labelledby="ml-readiness-title">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex gap-2">
            <BrainCircuit size={17} style={{ color: "var(--accent)", marginTop: 1 }} />
            <div>
              <h3 id="ml-readiness-title" className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Machine Learning Readiness</h3>
              <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Tracks complete, independent setup outcomes—not the total number of trades or scanner checks.</p>
            </div>
          </div>
          <span className="badge badge-blue">NO TRADING AUTHORITY</span>
        </div>
        {rankerError ? <p className="text-xs mt-4" style={{ color: "var(--negative)" }}>Could not load ML readiness.</p> : ranker ? (() => {
          const required = ranker.required ?? 1000;
          const usable = ranker.usable_episodes;
          const remaining = ranker.remaining ?? Math.max(0, required - usable);
          const pct = required > 0 ? Math.min(100, usable / required * 100) : 0;
          return <>
            <div className="grid grid-cols-3 gap-3 mt-4">
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Usable now</p><p className="text-xl font-semibold" style={{ color: "var(--ink)" }}>{usable}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Required</p><p className="text-xl font-semibold" style={{ color: "var(--ink)" }}>{required.toLocaleString()}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Still needed</p><p className="text-xl font-semibold" style={{ color: "var(--warning)" }}>{remaining.toLocaleString()}</p></div>
            </div>
            <div className="mt-3 h-2 rounded-full overflow-hidden" style={{ background: "var(--surface-raised)" }} role="progressbar" aria-valuenow={usable} aria-valuemin={0} aria-valuemax={required} aria-label="Usable ML episodes">
              <div className="h-full rounded-full" style={{ width: `${pct}%`, minWidth: usable > 0 ? 4 : 0, background: "var(--accent)" }} />
            </div>
            <p className="text-xs mt-2" style={{ color: "var(--ink-muted)" }}>{pct.toFixed(1)}% ready. The model remains off and cannot approve, reject, size, or place trades.</p>
            <p className="text-xs mt-3 pt-3 border-t" style={{ color: "var(--ink-faint)", borderColor: "var(--border)" }}>Current safety threshold: {required.toLocaleString()} usable episodes. Changing it to 500 requires a separate reviewed code change; this card reports the enforced value.</p>
          </>;
        })() : <p className="text-xs mt-4" style={{ color: "var(--ink-muted)" }}>Loading readiness…</p>}
      </section>

      {/* ── Emergency Controls ──────────────────────────────────────────── */}
      <div
        className="card p-4 flex flex-col gap-3"
        style={{
          borderColor: maintActive ? "rgba(251,113,133,0.4)" : "rgba(255,255,255,0.06)",
          background:  maintActive ? "rgba(239,68,68,0.06)" : undefined,
        }}
      >
        {/* Section header + status badge */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: "var(--ink)" }}>
            <AlertTriangle size={15} color={maintActive ? "#f87171" : "var(--ink-muted)"} />
            Emergency Controls
          </h3>
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{
              background: maintActive ? "rgba(239,68,68,0.15)" : "rgba(0,200,83,0.12)",
              color:      maintActive ? "#f87171" : "#00c853",
              border:     `1px solid ${maintActive ? "rgba(239,68,68,0.3)" : "rgba(0,200,83,0.25)"}`,
            }}
          >
            {maintActive ? "🔴 MAINTENANCE ACTIVE" : "✅ BOT OPERATIONAL"}
          </span>
        </div>

        <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          {maintActive
            ? (collectionOnly
              ? "Trading is halted for every user. Existing paper loops may only scan and record research data; no entries, exits, cancellations, or broker orders can be sent."
              : "Every bot loop is halted and all users see the maintenance screen. Type a new message below and save, or clear maintenance when ready.")
            : "Use when trading must stop for everyone. You can optionally keep existing paper loops collecting research data without allowing any orders."}
        </p>

        {/* Message / ETA input */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>
            Message shown to users (e.g. "Back online by 3 PM ET" or "Estimated downtime: 1–2 hours")
          </label>
          <textarea
            className="input"
            rows={2}
            style={{ fontSize: 13, resize: "vertical" }}
            placeholder="Describe the issue or give an estimated return time…"
            value={maintMessage}
            onChange={e => setMaintMessage(e.target.value)}
          />
        </div>

        {!maintActive && (
          <label className="flex items-start gap-2 text-xs" style={{ color: "var(--ink-muted)" }}>
            <input
              type="checkbox"
              checked={collectionOnly}
              onChange={e => setCollectionOnly(e.target.checked)}
              style={{ marginTop: 2 }}
            />
            <span>
              <strong style={{ color: "var(--ink)" }}>Keep paper research collection running</strong><br />
              Existing loops can scan and record signals/quotes. Every entry, exit, order cancellation, and broker order remains blocked.
            </span>
          </label>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 flex-wrap">
          {!maintActive ? (
            <button
              className="btn flex items-center gap-2"
              style={{
                background: "#dc2626", color: "#fff", border: "none",
                fontWeight: 700, flex: 1, minWidth: 200,
              }}
              onClick={enableMaintenance}
              disabled={maintWorking}
            >
              <AlertTriangle size={14} />
              {maintWorking ? "Halting all bots…" : "🔴 Halt All Trading for Maintenance"}
            </button>
          ) : (
            <>
              {/* Update message without disabling */}
              <button
                className="btn btn-ghost flex items-center gap-2"
                style={{ flex: 1, minWidth: 140 }}
                onClick={async () => {
                  setMaintWorking(true);
                  try {
                    // Re-enable with new message to update it
                    const r = await fetch("/api/admin/maintenance/enable", {
                      method: "POST", credentials: "include",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ message: maintMessage.trim(), collection_only: collectionOnly }),
                    });
                    if (r.ok) setMaintResult({ ok: true, msg: "Message updated." });
                  } catch { /* ignore */ } finally { setMaintWorking(false); }
                }}
                disabled={maintWorking}
              >
                Save Message
              </button>
              <button
                className="btn flex items-center gap-2"
                style={{
                  background: "#00c853", color: "#000", border: "none",
                  fontWeight: 700, flex: 1, minWidth: 140,
                }}
                onClick={disableMaintenance}
                disabled={maintWorking}
              >
                <CheckCircle2 size={14} />
                {maintWorking ? "Clearing…" : "✅ Clear — Bring Bot Back Online"}
              </button>
            </>
          )}
        </div>

        {maintResult && (
          <p className="text-xs" style={{ color: maintResult.ok ? "#00c853" : "#f87171" }}>
            {maintResult.msg}
          </p>
        )}
      </div>

      {/* Users list — card-per-user on mobile, table on larger screens */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          All Users
        </h3>
        {error && (
          <p className="text-xs mb-2" style={{ color: "#f87171" }}>{error}</p>
        )}
        {loading ? (
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>Loading…</p>
        ) : (
          <div className="flex flex-col gap-2">
            {users.map(u => (
              <div key={u.user_id}
                style={{
                  border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 8,
                  padding: "10px 12px",
                  background: resetState?.uid === u.user_id ? "rgba(0,200,83,0.03)" : undefined,
                }}
              >
                {/* User row */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  {/* Name + role */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
                      {u.username}
                    </span>
                    {u.user_id === user?.user_id && (
                      <span style={{ fontSize: 10, color: "var(--accent)", marginLeft: 6 }}>you</span>
                    )}
                    <span style={{
                      fontSize: 11, marginLeft: 8,
                      color: u.is_admin ? "var(--accent)" : "var(--ink-muted)",
                    }}>
                      {u.is_admin ? "Admin" : "Member"}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--ink-faint)", marginLeft: 8 }}>
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : ""}
                    </span>
                  </div>
                  {/* Actions */}
                  <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    <button
                      className="btn btn-ghost"
                      style={{ padding: "4px 10px", fontSize: 12 }}
                      title="Reset password"
                      onClick={() => {
                        setResetMsg(null);
                        setResetState(resetState?.uid === u.user_id
                          ? null
                          : { uid: u.user_id, uname: u.username, pw: "" });
                      }}
                    >
                      <KeyRound size={13} />
                    </button>
                    {u.user_id !== user?.user_id && (
                      <button
                        className="btn btn-ghost"
                        style={{ padding: "4px 10px", fontSize: 12, color: "var(--negative)" }}
                        title="Delete user"
                        onClick={() => deleteUser(u.user_id, u.username)}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>

                {/* Inline reset password — shown below user row on all screen sizes */}
                {resetState?.uid === u.user_id && (
                  <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                    <span style={{ fontSize: 12, color: "var(--ink-muted)" }}>
                      New password for <strong style={{ color: "var(--ink)" }}>{u.username}</strong>:
                    </span>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <input
                        type="password"
                        className="input"
                        style={{ fontSize: 12, padding: "4px 10px", flex: 1, minWidth: 160 }}
                        placeholder="12+ chars, upper, lower, number, special"
                        value={resetState.pw}
                        autoFocus
                        onChange={e => setResetState(s => s ? { ...s, pw: e.target.value } : null)}
                        onKeyDown={e => e.key === "Enter" && resetPassword()}
                      />
                      <button className="btn btn-primary" style={{ fontSize: 12, padding: "4px 12px" }} onClick={resetPassword}>
                        Set
                      </button>
                      <button className="btn btn-ghost" style={{ fontSize: 12, padding: "4px 10px" }}
                        onClick={() => { setResetState(null); setResetMsg(null); }}>
                        Cancel
                      </button>
                    </div>
                    <PasswordChecklist password={resetState.pw} style={{ paddingLeft: 2 }} />
                    {resetMsg && (
                      <span style={{ fontSize: 12, color: resetMsg.ok ? "var(--accent)" : "#f87171" }}>
                        {resetMsg.msg}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create user */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          Create User
        </h3>
        <div className="flex flex-col gap-3">
          {/* Stack inputs vertically on mobile */}
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              className="input flex-1"
              placeholder="Username"
              value={newUser.username}
              onChange={e => setNewUser(n => ({ ...n, username: e.target.value }))}
            />
            <input
              className="input flex-1"
              type="password"
              placeholder="12+ chars, upper, lower, number, special"
              value={newUser.password}
              onChange={e => setNewUser(n => ({ ...n, password: e.target.value }))}
            />
          </div>
          <PasswordChecklist password={newUser.password} style={{ paddingLeft: 2 }} />
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={newUser.is_admin}
              onChange={e => setNewUser(n => ({ ...n, is_admin: e.target.checked }))}
            />
            <span className="text-sm" style={{ color: "var(--ink)" }}>Grant admin access</span>
          </label>
          {createMsg && (
            <p className="text-xs" style={{ color: createMsg.ok ? "var(--accent)" : "#f87171" }}>
              {createMsg.msg}
            </p>
          )}
          <button className="btn btn-primary" onClick={createUser} disabled={creating}>
            <UserPlus size={14} />
            {creating ? "Creating…" : "Create User"}
          </button>
        </div>
      </div>

      {/* Invite link */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          Invite Link
        </h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Send this link to someone so they can create their own account and connect their
          own Alpaca/Tradier API keys. The link expires after the chosen period.
        </p>
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <label className="text-sm" style={{ color: "var(--ink)" }}>Expires in</label>
          <select
            className="select"
            value={inviteExp}
            onChange={e => setInviteExp(Number(e.target.value))}
          >
            <option value={24}>24 hours</option>
            <option value={48}>48 hours</option>
            <option value={72}>72 hours</option>
            <option value={168}>7 days</option>
          </select>
        </div>
        <button className="btn btn-primary mb-3" onClick={generateInvite} disabled={inviting} style={{ width: "100%" }}>
          <Link2 size={14} />
          {inviting ? "Generating…" : "Generate Invite Link"}
        </button>
        {inviteUrl && (
          <div className="flex flex-col gap-2">
            <div
              className="input text-xs font-mono"
              style={{ wordBreak: "break-all", userSelect: "all",
                background: "rgba(0,200,83,0.06)", borderColor: "rgba(0,200,83,0.2)" }}
            >
              {inviteUrl}
            </div>
            <button className="btn btn-ghost" onClick={copyInvite} style={{ width: "100%" }}>
              {copied ? "Copied!" : "Copy Link"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
