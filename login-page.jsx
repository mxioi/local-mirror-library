/* global React */
const { useState } = React;

function LoginPage({ onLogin, apiBase }) {
  const [authSource, setAuthSourceState] = useState(() => localStorage.getItem("login_auth_source") || "ad");
  const [username, setUsername]           = useState(() => localStorage.getItem("login_last_user") || "");
  const [password, setPassword]           = useState("");
  const [busy, setBusy]                   = useState(false);
  const [err, setErr]                     = useState("");
  const [showHelp, setShowHelp]           = useState(false);

  function changeAuthSource(val) {
    setAuthSourceState(val);
    localStorage.setItem("login_auth_source", val);
    setErr("");
    setPassword("");
    setShowHelp(false);
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`${apiBase}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, auth_source: authSource }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
      localStorage.setItem("login_last_user", username);
      onLogin(body.access_token, body.role, username);
    } catch (error) {
      setErr(error.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  const isAD = authSource === "ad";

  const kbd = (key) => (
    <kbd style={{background:"var(--paper)",border:"1px solid var(--line)",borderRadius:3,padding:"1px 5px",fontFamily:"monospace",fontSize:11}}>
      {key}
    </kbd>
  );

  return (
    <main style={{display:"grid",placeItems:"center",minHeight:"100vh",padding:16}}>
      <form onSubmit={submit} style={{width:"min(420px,100%)",background:"var(--paper)",border:"1px solid var(--line)",borderRadius:12,padding:"24px 24px 18px",display:"grid",gap:12}}>

        {/* Logo + title */}
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:4}}>
          <img src="logo.png" alt="logo"
            style={{height:40,width:"auto",objectFit:"contain",flexShrink:0}}
            onError={(e) => { e.target.style.display = "none"; }} />
          <div>
            <div style={{fontWeight:600,fontSize:16,lineHeight:1.2}}>Local Mirror Library</div>
            <div style={{fontSize:12,color:"var(--ink-faint)"}}>Sign in to continue</div>
          </div>
        </div>

        {/* Auth source dropdown */}
        <select value={authSource} onChange={(e) => changeAuthSource(e.target.value)}
          style={{padding:"6px 8px",borderRadius:6,border:"1px solid var(--line)",background:"var(--paper)",color:"var(--ink)",fontSize:13}}>
          <option value="ad">Active Directory</option>
          <option value="local">Local account</option>
        </select>

        {/* Username */}
        <input value={username} onChange={(e) => setUsername(e.target.value)}
          placeholder={isAD ? "username (without domain)" : "username"}
          autoComplete="username" required />

        {/* Password */}
        <input value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder={isAD ? "domain password" : "password"}
          type="password" autoComplete="current-password" required />

        {err && <div style={{color:"var(--err)",fontSize:12}}>{err}</div>}

        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        {/* Help toggle */}
        <button type="button" onClick={() => setShowHelp(h => !h)}
          style={{background:"none",border:"none",cursor:"pointer",color:"var(--ink-faint)",fontSize:12,textAlign:"left",padding:0}}>
          {showHelp ? "▾" : "▸"} Need help signing in?
        </button>

        {showHelp && (
          <div style={{background:"var(--surface,var(--line))",borderRadius:8,padding:"10px 12px",fontSize:12,color:"var(--ink-faint)",display:"grid",gap:6}}>
            {isAD ? (
              <>
                <strong style={{color:"var(--ink)"}}>Forgot or need to change your AD password?</strong>
                <p style={{margin:0}}>
                  On any domain-joined Windows machine press {kbd("Ctrl")} + {kbd("Alt")} + {kbd("Del")} then choose <em>Change a password</em>.
                </p>
                <p style={{margin:0}}>
                  If your account is locked out, ask your AD administrator to unlock it in <em>Active Directory Users &amp; Computers</em>.
                </p>
              </>
            ) : (
              <>
                <strong style={{color:"var(--ink)"}}>Forgot your local password?</strong>
                <p style={{margin:0}}>An administrator can reset it from the server command line:</p>
                <code style={{display:"block",background:"var(--paper)",border:"1px solid var(--line)",borderRadius:4,padding:"4px 8px",fontSize:11,wordBreak:"break-all"}}>
                  python archive_backend.py --set-password &lt;username&gt; &lt;newpassword&gt;
                </code>
                <p style={{margin:0}}>
                  Or once logged in as admin: <em>Operations → Admin → Users → Reset password</em>.
                </p>
              </>
            )}
          </div>
        )}

      </form>
    </main>
  );
}

window.LoginPage = LoginPage;
