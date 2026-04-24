/* global React */
const { useMemo, useState } = React;

function fmtAgo(iso) {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function StatTile({ label, value, sub, warn }) {
  return (
    <div style={{background:"var(--paper)",border:`1px solid ${warn ? "var(--warn)" : "var(--line)"}`,borderRadius:8,padding:"10px 14px",minWidth:0}}>
      <div style={{fontSize:11,color:"var(--ink-faint)",marginBottom:2}}>{label}</div>
      <div style={{fontSize:18,fontWeight:600,color: warn ? "var(--warn)" : "var(--ink)"}}>{value}</div>
      {sub && <div style={{fontSize:11,color:"var(--ink-faint)",marginTop:1}}>{sub}</div>}
    </div>
  );
}

function AdminPanel({ role, connected, users, adminSystem, adminLogs,
                      onCreateLocalUser, onUpdateUser, onResetPassword, onDeleteUser, onIssueApiKey,
                      onRefresh, onAdminSync, onAdminCleanup, onRefreshLogs }) {
  const [openCreate, setOpenCreate] = useState(false);
  const [username, setUsername]     = useState("");
  const [password, setPassword]     = useState("");
  const [userRole, setUserRole]     = useState("viewer");
  const [activeTab, setActiveTab]   = useState("users");

  const canAdmin = role === "admin";
  const sorted = useMemo(() =>
    [...(users || [])].sort((a, b) => String(a.username).localeCompare(String(b.username))),
    [users]
  );

  if (!canAdmin) {
    return <main className="main"><div className="empty"><h3>Admin only</h3><p>Your role cannot access this panel.</p></div></main>;
  }

  const sys = adminSystem;

  return (
    <main className="main">
      {/* Header */}
      <section className="hero" style={{marginBottom:16}}>
        <div>
          <h1>Admin Panel</h1>
          <p className="lede">Manage users, system health, and operations.</p>
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <button className="btn" onClick={() => onRefresh?.()} disabled={!connected}>Refresh</button>
          {activeTab === "users" && (
            <button className="btn primary" onClick={() => setOpenCreate(true)} disabled={!connected}>Create user</button>
          )}
        </div>
      </section>

      {/* Tabs */}
      <div style={{display:"flex",gap:0,borderBottom:"1px solid var(--line)",marginBottom:20}}>
        {["users","system","logs"].map(t => (
          <button key={t} onClick={() => setActiveTab(t)}
            style={{padding:"6px 16px",background:"none",border:"none",borderBottom: activeTab===t ? "2px solid var(--accent)" : "2px solid transparent",
              fontWeight: activeTab===t ? 600 : 400, color: activeTab===t ? "var(--ink)" : "var(--ink-faint)",
              cursor:"pointer",fontSize:13,textTransform:"capitalize"}}>
            {t}
          </button>
        ))}
      </div>

      {!connected ? (
        <div className="empty"><h3>Backend offline</h3><p>Start the API server to manage accounts.</p></div>
      ) : activeTab === "users" ? (

        /* ── USERS TAB ── */
        sorted.length === 0 ? (
          <div className="empty"><h3>No users</h3><p>Create a local user to get started.</p></div>
        ) : (
          <div style={{display:"grid",gap:10}}>
            {sorted.map((u) => (
              <div key={u.username} style={{background:"var(--paper)",border:"1px solid var(--line)",borderRadius:10,padding:"12px 16px"}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8,flexWrap:"wrap"}}>
                  <span style={{fontWeight:600,fontSize:14}}>{u.username}</span>
                  <span style={{fontSize:11,padding:"1px 7px",borderRadius:20,background:"var(--line)",color:"var(--ink-faint)"}}>{u.role}</span>
                  <span style={{fontSize:11,padding:"1px 7px",borderRadius:20,background:"var(--line)",color:"var(--ink-faint)"}}>{u.auth_source || "local"}</span>
                  {u.disabled && <span style={{fontSize:11,padding:"1px 7px",borderRadius:20,background:"var(--warn-bg)",color:"var(--warn)"}}>disabled</span>}
                  <span style={{marginLeft:"auto",fontSize:11,color:"var(--ink-faint)"}}>last login {fmtAgo(u.last_login_utc)}</span>
                </div>
                <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
                  <button className="btn sm" onClick={() =>
                    onUpdateUser?.(u.username, u.role === "viewer" ? "operator" : u.role === "operator" ? "admin" : "viewer", !!u.disabled)
                  }>Cycle role</button>
                  <button className="btn sm" onClick={() => onUpdateUser?.(u.username, u.role, !u.disabled)}>
                    {u.disabled ? "Enable" : "Disable"}
                  </button>
                  <button className="btn sm"
                    disabled={(u.auth_source || "local") !== "local"}
                    onClick={() => {
                      const np = window.prompt(`New password for ${u.username} (min 8 chars):`);
                      if (np && np.length >= 8) onResetPassword?.(u.username, np);
                      else if (np) alert("Password must be at least 8 characters.");
                    }}>
                    {(u.auth_source || "local") !== "local" ? "AD managed" : "Reset password"}
                  </button>
                  <button className="btn sm" onClick={() => onIssueApiKey?.(u.username)}>Issue API key</button>
                  <button className="btn danger sm" onClick={() => {
                    if (window.confirm(`Delete user "${u.username}"? This cannot be undone.`)) onDeleteUser?.(u.username);
                  }}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        )

      ) : activeTab === "system" ? (

        /* ── SYSTEM TAB ── */
        <div style={{display:"grid",gap:16}}>
          <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
            <button className="btn sm" onClick={() => onRefresh?.()}>Refresh stats</button>
            <button className="btn sm" onClick={() => onAdminSync?.()}>Sync config</button>
            <button className="btn sm" onClick={() => onAdminCleanup?.()}>Cleanup old jobs</button>
          </div>
          {sys ? (
            <>
              <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(130px,1fr))",gap:10}}>
                <StatTile label="Worker" value={sys.worker_running ? "Running" : "Stopped"} warn={!sys.worker_running} />
                <StatTile label="Items" value={sys.items?.total ?? 0} sub={`${sys.items?.pending ?? 0} pending`} />
                <StatTile label="Jobs queued" value={sys.jobs?.queued ?? 0} sub={`${sys.jobs?.running ?? 0} running`} />
                <StatTile label="Jobs failed" value={sys.jobs?.failed ?? 0} warn={(sys.jobs?.failed ?? 0) > 0} />
                <StatTile label="Active sessions" value={sys.users?.active_sessions ?? 0} sub={`${sys.users?.total ?? 0} users`} />
                <StatTile label="DB size" value={`${sys.db?.size_mb ?? 0} MB`} sub={`/ ${sys.db?.max_size_mb ?? 500} MB`} warn={sys.db?.warning} />
              </div>
              {sys.last_job && (
                <div style={{fontSize:12,color:"var(--ink-faint)"}}>
                  Last job: #{sys.last_job.id} · {sys.last_job.type} · <strong>{sys.last_job.status}</strong> · {fmtAgo(sys.last_job.finished_at_utc || sys.last_job.created_at_utc)}
                </div>
              )}
              <div style={{fontSize:11,color:"var(--ink-faint)"}}>Snapshot taken {fmtAgo(sys.time_utc)}</div>
            </>
          ) : (
            <p style={{color:"var(--ink-faint)",fontSize:13}}>No snapshot loaded — click Refresh stats.</p>
          )}
        </div>

      ) : (

        /* ── LOGS TAB ── */
        <div style={{display:"grid",gap:12}}>
          <button className="btn sm" style={{justifySelf:"start"}} onClick={() => onRefreshLogs?.()}>Refresh logs</button>
          <div style={{background:"var(--paper)",border:"1px solid var(--line)",borderRadius:8,padding:12,
            maxHeight:500,overflow:"auto",fontSize:11,fontFamily:"var(--t-mono,monospace)",
            color:"var(--ink-faint)",lineHeight:1.6,whiteSpace:"pre-wrap"}}>
            {(adminLogs || []).length === 0
              ? "No log lines loaded."
              : [...(adminLogs || [])].reverse().map((ln, i) => <div key={i}>{ln}</div>)
            }
          </div>
        </div>

      )}

      {/* Create user modal */}
      {openCreate && (
        <div className="drawer-scrim open" onClick={() => setOpenCreate(false)}>
          <div className="palette" onClick={(e) => e.stopPropagation()} style={{maxWidth:480}}>
            <div className="ops-head"><h2>Create local user</h2></div>
            <div className="op-form" style={{display:"grid",gap:10,marginTop:10}}>
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" autoFocus />
              <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" placeholder="temporary password (min 8 chars)" />
              <select value={userRole} onChange={(e) => setUserRole(e.target.value)}>
                <option value="viewer">viewer</option>
                <option value="operator">operator</option>
                <option value="admin">admin</option>
              </select>
              <div style={{display:"flex",justifyContent:"flex-end",gap:8}}>
                <button className="btn" onClick={() => setOpenCreate(false)}>Cancel</button>
                <button className="btn primary"
                  disabled={!username.trim() || password.length < 8}
                  onClick={() => {
                    onCreateLocalUser?.(username.trim(), password, userRole);
                    setUsername(""); setPassword(""); setUserRole("viewer");
                    setOpenCreate(false);
                  }}>Create</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

window.AdminPanel = AdminPanel;
