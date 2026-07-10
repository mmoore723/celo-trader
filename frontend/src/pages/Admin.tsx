/**
 * Admin.tsx — User management page (admin only).
 *
 * Features:
 *  - List all users
 *  - Create a user directly (username + password)
 *  - Generate an invite link for self-registration
 *  - Delete a user (cannot delete self)
 */
import { useState, useEffect } from "react";
import { UserPlus, Link2, Trash2, RefreshCw, KeyRound } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";

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

  // Create user form
  const [newUser, setNewUser]   = useState({ username: "", password: "", is_admin: false });
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  // Reset password inline state
  const [resetState, setResetState] = useState<{ uid: string; uname: string; pw: string } | null>(null);
  const [resetMsg,   setResetMsg]   = useState<{ ok: boolean; msg: string } | null>(null);

  // Invite
  const [inviteUrl, setInviteUrl]   = useState<string | null>(null);
  const [inviteExp, setInviteExp]   = useState<number>(48);
  const [inviting, setInviting]     = useState(false);
  const [copied, setCopied]         = useState(false);

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
    if (!resetState || resetState.pw.length < 6) {
      setResetMsg({ ok: false, msg: "Min 6 characters" });
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
    <div className="p-4 max-w-2xl flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>
          User Management
        </h2>
        <button className="btn btn-ghost" onClick={loadUsers}>
          <RefreshCw size={13} />
        </button>
      </div>

      {/* Users table */}
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
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                {["Username", "Role", "Created", ""].map(h => (
                  <th key={h} style={{
                    textAlign: "left", padding: "4px 8px",
                    fontSize: 11, color: "var(--ink-muted)", fontWeight: 500
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <>
                  <tr key={u.user_id}
                    style={{ borderBottom: resetState?.uid === u.user_id ? "none" : "1px solid rgba(255,255,255,0.04)" }}>
                    <td style={{ padding: "8px 8px", fontSize: 13, color: "var(--ink)" }}>
                      {u.username}
                      {u.user_id === user?.user_id && (
                        <span style={{ fontSize: 10, color: "var(--accent)", marginLeft: 6 }}>you</span>
                      )}
                    </td>
                    <td style={{ padding: "8px 8px", fontSize: 12,
                      color: u.is_admin ? "var(--accent)" : "var(--ink-muted)" }}>
                      {u.is_admin ? "Admin" : "Member"}
                    </td>
                    <td style={{ padding: "8px 8px", fontSize: 11, color: "var(--ink-muted)" }}>
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td style={{ padding: "8px 8px" }}>
                      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                        {/* Reset password — available for all users including self */}
                        <button
                          className="btn btn-ghost"
                          style={{ padding: "2px 8px", fontSize: 12 }}
                          title="Reset password"
                          onClick={() => {
                            setResetMsg(null);
                            setResetState(resetState?.uid === u.user_id
                              ? null
                              : { uid: u.user_id, uname: u.username, pw: "" });
                          }}
                        >
                          <KeyRound size={12} />
                        </button>
                        {/* Delete — not allowed for self */}
                        {u.user_id !== user?.user_id && (
                          <button
                            className="btn btn-ghost"
                            style={{ padding: "2px 8px", fontSize: 12 }}
                            title="Delete user"
                            onClick={() => deleteUser(u.user_id, u.username)}
                          >
                            <Trash2 size={12} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {/* Inline reset password row */}
                  {resetState?.uid === u.user_id && (
                    <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", background: "rgba(0,200,83,0.03)" }}>
                      <td colSpan={4} style={{ padding: "6px 8px 10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 12, color: "var(--ink-muted)", whiteSpace: "nowrap" }}>
                            New password for <strong style={{ color: "var(--ink)" }}>{u.username}</strong>:
                          </span>
                          <input
                            type="password"
                            className="input"
                            style={{ fontSize: 12, padding: "4px 10px", width: 180 }}
                            placeholder="Min 6 characters"
                            value={resetState.pw}
                            autoFocus
                            onChange={e => setResetState(s => s ? { ...s, pw: e.target.value } : null)}
                            onKeyDown={e => e.key === "Enter" && resetPassword()}
                          />
                          <button className="btn btn-primary" style={{ fontSize: 12, padding: "4px 12px" }} onClick={resetPassword}>
                            Set
                          </button>
                          <button className="btn btn-ghost" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => { setResetState(null); setResetMsg(null); }}>
                            Cancel
                          </button>
                          {resetMsg && (
                            <span style={{ fontSize: 12, color: resetMsg.ok ? "var(--accent)" : "#f87171" }}>
                              {resetMsg.msg}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create user */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          Create User
        </h3>
        <div className="flex flex-col gap-3">
          <div className="flex gap-2">
            <input
              className="input flex-1"
              placeholder="Username"
              value={newUser.username}
              onChange={e => setNewUser(n => ({ ...n, username: e.target.value }))}
            />
            <input
              className="input flex-1"
              type="password"
              placeholder="Password"
              value={newUser.password}
              onChange={e => setNewUser(n => ({ ...n, password: e.target.value }))}
            />
          </div>
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
        <div className="flex items-center gap-2 mb-3">
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
        <button className="btn btn-primary mb-3" onClick={generateInvite} disabled={inviting}>
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
            <button className="btn btn-ghost" onClick={copyInvite}>
              {copied ? "Copied!" : "Copy Link"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
