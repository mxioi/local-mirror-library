/* global React, ReactDOM, ARCHIVE_DATA, ARCHIVE_JOBS, ARCHIVE_API_BASE, Drawer, Ops, Toasts, Palette, LoginPage, AdminPanel,
          useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakToggle, TweakSelect */
const { useState, useEffect, useMemo, useRef, useCallback } = React;
const { Icon, IC, Card, ListRow, StatusBadge, fmtAgo, fmtBytes } = window.LibraryPrimitives;
const DEFAULT_API_BASE = (() => {
  const host = (window.location && window.location.hostname) || "";
  const proto = window.location && window.location.protocol === "https:" ? "https:" : "http:";
  return host ? `${proto}//${host}:8010/api/v1` : "http://127.0.0.1:8010/api/v1";
})();
const API_BASE = (window.ARCHIVE_API_BASE || DEFAULT_API_BASE).replace(/\/$/, "");
const SignInComponent = window.LoginPage || LoginGate;
const AdminPanelComponent = window.AdminPanel || (() => <main className="main"><div className="empty"><h3>Admin panel unavailable</h3><p>Missing admin-panel.jsx</p></div></main>);

function mapItemStatus(s) {
  if (s === "archived") return "fresh";
  if (s === "pending") return "queued";
  if (s === "missing") return "stale";
  if (s === "deleted") return "stale";
  return s || "queued";
}

function normPage(item) {
  const localHref = item.output_path || "";
  const sourceUrl = item.source_url || "";
  const host = item.source_host || (sourceUrl ? (() => { try { return new URL(sourceUrl).host; } catch { return "unknown"; } })() : "unknown");
  return {
    id: item.id,
    slug: `item-${item.id}`,
    title: item.title,
    oldid: item.oldid || null,
    collection: item.collection || "Wikipedia",
    tags: Array.isArray(item.tags) ? item.tags : [],
    status: mapItemStatus(item.status),
    source_type: item.source_type || "wikipedia",
    source_url: sourceUrl,
    host,
    archived_at_utc: item.archived_at_utc || null,
    size_bytes: item.file_size_bytes || 0,
    checksum: item.checksum || null,
    retention: item.retention || "indefinite",
    owner: item.owner || "system",
    change_count: item.change_count || 0,
    last_run: item.last_run || null,
    local_href: localHref || null,
    audit: item.audit || [],
    timeline: Array.isArray(item.timeline)
      ? item.timeline.map((t) => ({
          id: t.id,
          oldid: t.oldid || null,
          archived_at_utc: t.archived_at_utc || null,
          status: mapItemStatus(t.status),
          local_href: t.output_path || null,
          is_current: !!t.is_current,
          file_size_bytes: t.file_size_bytes || 0,
        }))
      : [],
  };
}

function mapJob(j) {
  const state = j.status === "completed" ? "complete" : j.status;
  const payload = j.payload || {};
  const target = payload.title || payload.url || "—";
  const started = j.started_at_utc || j.created_at_utc;
  let duration_ms;
  if (j.started_at_utc && j.finished_at_utc) {
    const a = new Date(j.started_at_utc).getTime();
    const b = new Date(j.finished_at_utc).getTime();
    if (!Number.isNaN(a) && !Number.isNaN(b) && b >= a) duration_ms = b - a;
  }
  return {
    id: `job-${j.id}`,
    job_id: j.id,
    action: j.type,
    target,
    state,
    started,
    by: j.requested_by || "system",
    duration_ms,
    progress: j.progress,
    error: j.error_text || null,
  };
}

async function api(path, options = {}, token = "") {
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!headers["Content-Type"] && options.body) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    const err = new Error(`Failed to reach API at ${API_BASE}. Check backend host/port and CORS origin.`);
    err.status = 0;
    throw err;
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body.detail || body.error || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}

function LoginGate({ onLogin }) {
  const [authSource, setAuthSourceState] = useState(() => localStorage.getItem("login_auth_source") || "ad");
  const [username, setUsername] = useState(() => localStorage.getItem("login_last_user") || "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showHelp, setShowHelp] = useState(false);

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
      const res = await api(`/auth/login`, { method: "POST", body: JSON.stringify({ username, password, auth_source: authSource }) });
      localStorage.setItem("login_last_user", username);
      onLogin(res.access_token, res.role, username);
    } catch (error) {
      setErr(error.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  const isAD = authSource === "ad";

  return (
    <main style={{display:"grid",placeItems:"center",minHeight:"100vh",padding:16}}>
      <form onSubmit={submit} style={{width:"min(420px,100%)",background:"var(--paper)",border:"1px solid var(--line)",borderRadius:12,padding:"24px 24px 18px",display:"grid",gap:12}}>
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:4}}>
          <img src="logo.png" alt="logo" style={{height:40,width:"auto",objectFit:"contain"}} onError={(e)=>{e.target.style.display="none"}} />
          <div>
            <div style={{fontWeight:600,fontSize:16,lineHeight:1.2}}>Local Mirror Library</div>
            <div style={{fontSize:12,color:"var(--ink-faint)"}}>Sign in to continue</div>
          </div>
        </div>

        <select value={authSource} onChange={(e)=>changeAuthSource(e.target.value)}
          style={{padding:"6px 8px",borderRadius:6,border:"1px solid var(--line)",background:"var(--paper)",color:"var(--ink)",fontSize:13}}>
          <option value="ad">Active Directory</option>
          <option value="local">Local account</option>
        </select>

        <input value={username} onChange={(e)=>setUsername(e.target.value)}
          placeholder={isAD ? "username (without domain)" : "username"} autoComplete="username" required />

        <input value={password} onChange={(e)=>setPassword(e.target.value)}
          placeholder={isAD ? "domain password" : "password"} type="password" autoComplete="current-password" required />

        {err && <div style={{color:"var(--err)",fontSize:12}}>{err}</div>}

        <button className="btn primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>

        <button type="button" onClick={() => setShowHelp(h => !h)}
          style={{background:"none",border:"none",cursor:"pointer",color:"var(--ink-faint)",fontSize:12,textAlign:"left",padding:0}}>
          {showHelp ? "▾" : "▸"} Need help signing in?
        </button>

        {showHelp && (
          <div style={{background:"var(--paper-raised,var(--line))",borderRadius:8,padding:"10px 12px",fontSize:12,color:"var(--ink-secondary,var(--ink-faint))",display:"grid",gap:6}}>
            {isAD ? (
              <>
                <strong style={{color:"var(--ink)"}}>Forgot or need to change your AD password?</strong>
                <p style={{margin:0}}>On any domain-joined Windows machine press <kbd style={{background:"var(--paper)",border:"1px solid var(--line)",borderRadius:3,padding:"1px 4px",fontFamily:"monospace"}}>Ctrl</kbd> + <kbd style={{background:"var(--paper)",border:"1px solid var(--line)",borderRadius:3,padding:"1px 4px",fontFamily:"monospace"}}>Alt</kbd> + <kbd style={{background:"var(--paper)",border:"1px solid var(--line)",borderRadius:3,padding:"1px 4px",fontFamily:"monospace"}}>Del</kbd> then choose <em>Change a password</em>.</p>
                <p style={{margin:0}}>If your account is locked out, ask your AD administrator to unlock it in Active Directory Users &amp; Computers.</p>
              </>
            ) : (
              <>
                <strong style={{color:"var(--ink)"}}>Forgot your local password?</strong>
                <p style={{margin:0}}>An administrator can reset it from the server command line:</p>
                <code style={{display:"block",background:"var(--paper)",border:"1px solid var(--line)",borderRadius:4,padding:"4px 8px",fontSize:11,wordBreak:"break-all"}}>
                  python archive_backend.py --set-password &lt;username&gt; &lt;newpassword&gt;
                </code>
                <p style={{margin:0}}>Or from the Admin panel once logged in: go to <em>Operations → Admin → Users</em> and use the reset password button.</p>
              </>
            )}
          </div>
        )}
      </form>
    </main>
  );
}

// ------------------------------------------------------------------
// Tweaks defaults — these are user-facing toggles, persisted by host
// ------------------------------------------------------------------
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "defaultView": "grid",
  "theme": "paper",
  "showFilterBar": true,
  "showOpsByDefault": true
}/*EDITMODE-END*/;

// ------------------------------------------------------------------
// App
// ------------------------------------------------------------------
function App() {
  const [tv, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("archive_token") || "");
  const [role, setRole] = useState(() => localStorage.getItem("archive_role") || "viewer");
  const [actor, setActor] = useState(() => localStorage.getItem("archive_user") || "frontend-user");
  const [authSource, setAuthSource] = useState(() => localStorage.getItem("archive_auth_source") || "");

  // State ------------------------------------------------------------
  const [pages, setPages]     = useState(() => ARCHIVE_DATA.pages);
  const [jobs, setJobs]       = useState(() => ARCHIVE_JOBS);
  const [historyRows, setHistoryRows] = useState([]);
  const [connected, setConnected] = useState(false);
  const [facets, setFacets] = useState({ collections: [], statuses: [], sources: [], tags: [] });
  const [query, setQuery]     = useState("");
  const [collection, setColl] = useState("all");
  const [status, setStatus]   = useState("any");
  const [sourceType, setSrc]  = useState("any");
  const [activeTags, setTags] = useState(new Set());
  const [sort, setSort]       = useState("archived_desc");
  const [view, setView]       = useState(tv.defaultView);
  const [opsOpen, setOpsOpen] = useState(tv.showOpsByDefault);
  const [mainTab, setMainTab] = useState("library");
  const [opsTab, setOpsTab] = useState("run");
  const [opened, setOpened]   = useState(null);  // slug of page opened in drawer
  const [detailItem, setDetailItem] = useState(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window !== "undefined" && window.innerWidth > 780);
  const [profileOpen, setProfileOpen] = useState(false);
  const [themeMode, setThemeMode] = useState(() => localStorage.getItem("theme_mode") || "system");
  const [avatarUrl, setAvatarUrl] = useState(() => localStorage.getItem("profile_avatar") || "");
  const [userEmail, setUserEmail] = useState(() => localStorage.getItem("profile_email") || "");
  const avatarInputRef = useRef(null);
  const [toasts, setToasts]   = useState([]);
  const [saved, setSaved]     = useState([]);
  const [adminUsers, setAdminUsers] = useState([]);
  const [adminSystem, setAdminSystem] = useState(null);
  const [adminLogs, setAdminLogs] = useState([]);
  const [apiOffline, setApiOffline] = useState(false);
  const apiOfflineRef = useRef(false);
  const settingsLoadedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function loadDetail() {
      if (!opened || !connected) {
        setDetailItem(null);
        return;
      }
      const base = pages.find(p => p.slug === opened);
      if (!base?.id) {
        setDetailItem(base || null);
        return;
      }
      try {
        const res = await api(`/items/${base.id}`, { method: "GET" }, authToken);
        if (!cancelled) setDetailItem(normPage(res.item || {}));
      } catch {
        if (!cancelled) setDetailItem(base);
      }
    }
    loadDetail();
    return () => { cancelled = true; };
  }, [opened, pages, connected, role, authToken]);

  // Sync view/ops from tweaks when they change
  useEffect(() => { apiOfflineRef.current = apiOffline; }, [apiOffline]);
  useEffect(() => { setView(tv.defaultView); }, [tv.defaultView]);
  useEffect(() => { setOpsOpen(tv.showOpsByDefault); }, [tv.showOpsByDefault]);
  useEffect(() => {
    if (mainTab === "admin" && role !== "admin") setMainTab("library");
  }, [mainTab, role]);

  // Apply theme — resolves "system" via matchMedia
  useEffect(() => {
    const apply = () => {
      let resolved = themeMode === "dark" ? "dark" : themeMode === "system"
        ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "paper")
        : "paper";
      document.documentElement.dataset.theme = resolved;
      document.documentElement.dataset.themeMode = themeMode;
      document.documentElement.dataset.density = tv.density;
    };
    apply();
    if (themeMode === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
  }, [themeMode, tv.density]);

  // Derived counts & facet options ---------------------------------
  const collectionCounts = useMemo(() => {
    if (connected && facets.collections?.length) {
      const m = new Map();
      facets.collections.forEach(x => m.set(x.name, x.count));
      return m;
    }
    const m = new Map();
    pages.forEach(p => m.set(p.collection, (m.get(p.collection) || 0) + 1));
    return m;
  }, [pages, connected, facets]);

  const tagCounts = useMemo(() => {
    if (connected && facets.tags?.length) {
      return facets.tags.map(t => [t.name, t.count]).sort((a,b) => b[1] - a[1]);
    }
    const m = new Map();
    pages.forEach(p => p.tags.forEach(t => m.set(t, (m.get(t) || 0) + 1)));
    return [...m.entries()].sort((a,b) => b[1] - a[1]);
  }, [pages, connected, facets]);

  const statusCounts = useMemo(() => {
    if (connected && facets.statuses?.length) {
      const map = { fresh: 0, stale: 0, queued: 0, failed: 0 };
      facets.statuses.forEach(s => {
        const k = mapItemStatus(s.name);
        if (map[k] != null) map[k] += s.count;
      });
      return map;
    }
    const m = { fresh: 0, stale: 0, queued: 0, failed: 0 };
    pages.forEach(p => { if (m[p.status] != null) m[p.status]++; });
    return m;
  }, [pages, connected, facets]);

  const sourceCounts = useMemo(() => {
    if (connected && facets.sources?.length) {
      const m = new Map();
      facets.sources.forEach(s => m.set(s.name, s.count));
      return m;
    }
    const m = new Map();
    pages.forEach(p => m.set(p.source_type, (m.get(p.source_type) || 0) + 1));
    return m;
  }, [pages, connected, facets]);

  const knownTags = useMemo(() => {
    if (connected && facets.tags?.length) {
      return facets.tags.map((t) => t.name).filter(Boolean);
    }
    const s = new Set();
    pages.forEach((p) => (p.tags || []).forEach((t) => s.add(t)));
    return [...s].sort();
  }, [pages, connected, facets]);

  // Filtering / sorting --------------------------------------------
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = pages.filter(p => {
      if (collection !== "all" && p.collection !== collection) return false;
      if (status !== "any" && p.status !== status) return false;
      if (sourceType !== "any" && p.source_type !== sourceType && p.host !== sourceType) return false;
      if (activeTags.size > 0 && !p.tags.some(t => activeTags.has(t))) return false;
      if (!q) return true;
      return (
        p.title.toLowerCase().includes(q) ||
        (p.oldid || "").includes(q) ||
        p.host.toLowerCase().includes(q) ||
        p.tags.some(t => t.toLowerCase().includes(q)) ||
        p.collection.toLowerCase().includes(q)
      );
    });
    list.sort((a, b) => {
      if (sort === "archived_desc") return (b.archived_at_utc || "").localeCompare(a.archived_at_utc || "");
      if (sort === "archived_asc")  return (a.archived_at_utc || "").localeCompare(b.archived_at_utc || "");
      if (sort === "title_asc")     return a.title.localeCompare(b.title);
      if (sort === "size_desc")     return (b.size_bytes || 0) - (a.size_bytes || 0);
      return 0;
    });
    return list;
  }, [pages, query, collection, status, sourceType, activeTags, sort]);

  // Active filter chips --------------------------------------------
  const activeFilters = useMemo(() => {
    const f = [];
    if (collection !== "all") f.push({ key: "collection", val: collection, clear: () => setColl("all") });
    if (status !== "any") f.push({ key: "status", val: status, clear: () => setStatus("any") });
    if (sourceType !== "any") f.push({ key: "source", val: sourceType, clear: () => setSrc("any") });
    [...activeTags].forEach(t => f.push({ key: "tag", val: t, clear: () => {
      const s = new Set(activeTags); s.delete(t); setTags(s);
    }}));
    if (query) f.push({ key: "q", val: `"${query}"`, clear: () => setQuery("") });
    return f;
  }, [collection, status, sourceType, activeTags, query]);

  // Toast helper
  const toast = useCallback((text, kind = "info") => {
    setToasts(t => {
      if (t.some(x => x.text === text)) return t;
      const id = Math.random().toString(36).slice(2);
      setTimeout(() => setToasts(u => u.filter(x => x.id !== id)), 3500);
      return [...t, { id, text, kind }];
    });
  }, []);

  const authedApi = useCallback(async (path, options = {}) => {
    try {
      const res = await api(path, options, authToken);
      if (apiOfflineRef.current) setApiOffline(false);
      return res;
    } catch (err) {
      if (err?.status === 0) {
        if (!apiOfflineRef.current) setApiOffline(true);
      }
      if (err?.status === 401) {
        localStorage.removeItem("archive_token");
        localStorage.removeItem("archive_role");
        localStorage.removeItem("archive_user");
        setAuthToken("");
        setConnected(false);
        setRole("viewer");
        setActor("frontend-user");
        setAuthSource("");
        toast("Session expired. Please sign in again.", "warn");
      }
      throw err;
    }
  }, [authToken, toast]);

  const loadPages = useCallback(async () => {
    const collectionParam = collection === "all" ? "" : `&collection=${encodeURIComponent(collection)}`;
    const statusParam = status === "any" ? "" : `&status=${encodeURIComponent(status === "fresh" ? "archived" : status === "queued" ? "pending" : status === "stale" ? "missing" : status)}`;
    const sourceParam = sourceType === "any" ? "" : `&source=${encodeURIComponent(sourceType)}`;
    const qParam = "";
    const sortMap = {
      archived_desc: ["archived_at", "desc"],
      archived_asc: ["archived_at", "asc"],
      title_asc: ["title", "asc"],
      size_desc: ["size", "desc"],
    };
    const [sortKey, orderKey] = sortMap[sort] || ["archived_at", "desc"];
    const tag = [...activeTags][0] || "";
    const tagParam = tag ? `&tag=${encodeURIComponent(tag)}` : "";
    const res = await authedApi(
      `/items?${qParam}sort=${sortKey}&order=${orderKey}&limit=500&offset=0${collectionParam}${statusParam}${sourceParam}${tagParam}`,
      { method: "GET" },
    );
    setPages((res.items || []).map(normPage));
  }, [collection, status, sourceType, query, sort, activeTags, authedApi]);

  const loadFacets = useCallback(async () => {
    const res = await authedApi(`/facets`, { method: "GET" });
    setFacets(res || { collections: [], statuses: [], sources: [], tags: [] });
  }, [authedApi]);

  const loadJobs = useCallback(async () => {
    const res = await authedApi(`/jobs?limit=60&offset=0`, { method: "GET" });
    setJobs((res.jobs || []).map(mapJob));
  }, [authedApi]);

  const loadHistory = useCallback(async () => {
    const res = await authedApi(`/history?limit=120&offset=0`, { method: "GET" });
    setHistoryRows(res.history || []);
  }, [authedApi]);

  const loadSavedFilters = useCallback(async () => {
    const res = await authedApi(`/saved-filters`, { method: "GET" });
    const parsed = (res.filters || []).map((f, idx) => {
      let q = {};
      try { q = JSON.parse(f.query_json || "{}"); } catch { q = {}; }
      return {
        id: f.id || `saved-${idx}`,
        name: f.name,
        collection: q.collection || "all",
        status: q.status || "any",
        source: q.source || "any",
        q: q.q || "",
        tags: Array.isArray(q.tags) ? q.tags : [],
      };
    });
    setSaved(parsed);
  }, [authedApi]);

  const loadAdminUsers = useCallback(async () => {
    if (!connected || role !== "admin") {
      setAdminUsers([]);
      return;
    }
    const res = await authedApi(`/admin/users`, { method: "GET" });
    setAdminUsers(res.users || []);
  }, [connected, role, authedApi]);

  const loadAdminSystem = useCallback(async () => {
    if (!connected || role !== "admin") {
      setAdminSystem(null);
      return;
    }
    const res = await authedApi(`/admin/system`, { method: "GET" });
    setAdminSystem(res || null);
  }, [connected, role, authedApi]);

  const loadBackend = useCallback(async () => {
    try {
      const me = await authedApi(`/auth/me`, { method: "GET" });
      if (me?.role && me.role !== role) setRole(me.role);
      if (me?.actor && me.actor !== actor) setActor(me.actor);
      const nextSource = me?.profile?.auth_source || "";
      if (nextSource !== authSource) {
        setAuthSource(nextSource);
        if (nextSource) localStorage.setItem("archive_auth_source", nextSource);
        else localStorage.removeItem("archive_auth_source");
      }
      setConnected(true);
      await Promise.all([loadFacets(), loadJobs(), loadSavedFilters(), loadHistory()]);
      if (me?.role === "admin") {
        await Promise.all([
          loadAdminUsers().catch(() => {}),
          loadAdminSystem().catch(() => {}),
        ]);
      }
    } catch (err) {
      setConnected(false);
      if (err?.status === 0) {
        toast("API is unreachable — check the backend is running.", "warn");
      } else if (err?.status !== 401) {
        toast(`Failed to connect: ${err.message}`, "warn");
      }
    }
  }, [role, actor, authSource, loadFacets, loadJobs, loadSavedFilters, loadHistory, loadAdminUsers, loadAdminSystem, toast, authedApi]);

  useEffect(() => {
    loadAdminUsers().catch(() => {});
  }, [loadAdminUsers]);

  useEffect(() => {
    loadAdminSystem().catch(() => {});
  }, [loadAdminSystem]);

  const upsertAdminUser = useCallback(async (username, userRole, disabled) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      await authedApi(
        `/admin/users`,
        { method: "POST", body: JSON.stringify({ username, role: userRole, disabled }) },
      );
      toast(`Updated user ${username}`, "info");
      await loadAdminUsers();
    } catch (err) {
      toast(`User update failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadAdminUsers, toast]);

  const createLocalUser = useCallback(async (username, password, userRole) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      await authedApi(`/admin/users`, {
        method: "POST",
        body: JSON.stringify({ username, role: userRole, disabled: false, password, auth_source: "local" }),
      });
      toast(`Created local user ${username}`, "info");
      await loadAdminUsers();
    } catch (err) {
      toast(`Create user failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadAdminUsers, toast]);

  const deleteAdminUser = useCallback(async (username) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      await authedApi(`/admin/users/${encodeURIComponent(username)}`, { method: "DELETE" });
      toast(`Deleted user ${username}`, "warn");
      await loadAdminUsers();
    } catch (err) {
      toast(`User delete failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadAdminUsers, toast]);

  const issueAdminApiKey = useCallback(async (username) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      const res = await authedApi(`/admin/users/${encodeURIComponent(username)}/api-key`, { method: "POST" });
      const key = String(res?.api_key || "");
      if (!key) {
        toast("API key issue succeeded but key missing.", "warn");
        return;
      }
      window.prompt(`One-time API key for ${username}. Copy it now:`, key);
      toast(`Issued API key for ${username}`, "info");
    } catch (err) {
      toast(`API key issue failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, toast]);

  const changeOwnPassword = useCallback(async (oldPassword, newPassword) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      await authedApi(`/auth/change-password`, {
        method: "POST",
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      toast("Password updated.", "info");
    } catch (err) {
      toast(`Password update failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, toast]);

  const resetAdminPassword = useCallback(async (username, newPassword) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      await authedApi(`/admin/users/${encodeURIComponent(username)}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ new_password: newPassword }),
      });
      toast(`Password reset for ${username}`, "info");
    } catch (err) {
      toast(`Reset failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, toast]);

  const retryJob = useCallback(async (jobId) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      const res = await authedApi(`/jobs/${jobId}/retry`, { method: "POST" });
      toast(`Retry queued as job #${res.job_id}`, "info");
      await Promise.all([loadJobs(), loadHistory(), loadAdminSystem()]);
    } catch (err) {
      toast(`Retry failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadJobs, loadHistory, loadAdminSystem, toast]);

  const cancelJob = useCallback(async (jobId) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      await authedApi(`/jobs/${jobId}/cancel`, { method: "POST" });
      toast(`Cancelled job #${jobId}`, "warn");
      await Promise.all([loadJobs(), loadHistory(), loadAdminSystem()]);
    } catch (err) {
      toast(`Cancel failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadJobs, loadHistory, loadAdminSystem, toast]);

  const getJobDetail = useCallback(async (jobId) => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return null;
    }
    try {
      const res = await authedApi(`/jobs/${jobId}`, { method: "GET" });
      return res.job || null;
    } catch (err) {
      toast(`Load job detail failed: ${err.message}`, "err");
      return null;
    }
  }, [connected, authedApi, toast]);

  const refreshAdminSystem = useCallback(async () => {
    try {
      await loadAdminSystem();
    } catch (err) {
      toast(`System refresh failed: ${err.message}`, "err");
    }
  }, [loadAdminSystem, toast]);

  const runAdminSync = useCallback(async () => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      const res = await authedApi(`/admin/sync`, { method: "POST" });
      toast(`Sync completed: inserted ${res?.stats?.inserted || 0}, updated ${res?.stats?.updated || 0}`, "info");
      await Promise.all([loadPages(), loadFacets(), loadHistory(), loadAdminSystem()]);
    } catch (err) {
      toast(`Admin sync failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadPages, loadFacets, loadHistory, loadAdminSystem, toast]);

  const runAdminCleanup = useCallback(async () => {
    if (!connected) return;
    try {
      const res = await authedApi(`/admin/cleanup`, { method: "POST", body: JSON.stringify({ purge_old_jobs: true, days: 30 }) });
      toast(`Cleanup removed ${res.removed_jobs || 0} old jobs.`, "info");
      await Promise.all([loadJobs(), loadHistory(), loadAdminSystem()]);
    } catch (err) {
      toast(`Cleanup failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadJobs, loadHistory, loadAdminSystem, toast]);

  const loadAdminLogs = useCallback(async () => {
    if (!connected || role !== "admin") {
      setAdminLogs([]);
      return;
    }
    try {
      const res = await authedApi(`/admin/logs?lines=200`, { method: "GET" });
      setAdminLogs(Array.isArray(res.lines) ? res.lines : []);
    } catch (err) {
      if (err?.status !== 0) toast(`Load logs failed: ${err.message}`, "err");
    }
  }, [connected, role, authedApi, toast]);

  useEffect(() => {
    loadAdminLogs().catch(() => {});
  }, [loadAdminLogs]);

  const refreshAdminPanel = useCallback(async () => {
    await Promise.all([loadAdminUsers(), loadAdminSystem(), loadAdminLogs()]);
  }, [loadAdminUsers, loadAdminSystem, loadAdminLogs]);

  const exportHistoryCsv = useCallback(async () => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/history.csv?limit=2000`, {
        method: "GET",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(txt || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      a.href = href;
      a.download = `archive-history-${stamp}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
      toast("History CSV exported.", "info");
    } catch (err) {
      toast(`History export failed: ${err.message}`, "err");
    }
  }, [connected, authToken, toast]);

  const retryAllFailedJobs = useCallback(async () => {
    if (!connected) {
      toast("Backend not connected.", "err");
      return;
    }
    try {
      const res = await authedApi(`/jobs/retry-failed?limit=500`, { method: "POST" });
      toast(`Queued ${res.queued || 0} failed jobs for retry.`, "info");
      await Promise.all([loadJobs(), loadHistory(), loadAdminSystem()]);
    } catch (err) {
      toast(`Retry-all failed: ${err.message}`, "err");
    }
  }, [connected, authedApi, loadJobs, loadHistory, loadAdminSystem, toast]);

  const addItemTag = useCallback(async (itemId, tag) => {
    try {
      await authedApi(`/items/${itemId}/tags`, { method: "POST", body: JSON.stringify({ tag }) });
      await Promise.all([loadPages(), loadFacets(), loadHistory()]);
      const res = await authedApi(`/items/${itemId}`, { method: "GET" });
      setDetailItem(normPage(res.item || {}));
      toast(`Added tag #${tag}`, "info");
    } catch (err) {
      toast(`Add tag failed: ${err.message}`, "err");
    }
  }, [authedApi, loadPages, loadFacets, loadHistory, toast]);

  const removeItemTag = useCallback(async (itemId, tag) => {
    try {
      await authedApi(`/items/${itemId}/tags/${encodeURIComponent(tag)}`, { method: "DELETE" });
      await Promise.all([loadPages(), loadFacets(), loadHistory()]);
      const res = await authedApi(`/items/${itemId}`, { method: "GET" });
      setDetailItem(normPage(res.item || {}));
      toast(`Removed tag #${tag}`, "warn");
    } catch (err) {
      toast(`Remove tag failed: ${err.message}`, "err");
    }
  }, [authedApi, loadPages, loadFacets, loadHistory, toast]);

  const deleteItem = useCallback(async (itemId, reason) => {
    try {
      await authedApi(`/items/${itemId}`, { method: "DELETE", body: JSON.stringify({ reason }) });
      toast("Item deleted.", "warn");
      setOpened(null);
      await Promise.all([loadPages(), loadFacets(), loadHistory()]);
    } catch (err) {
      toast(`Delete failed: ${err.message}`, "err");
    }
  }, [authedApi, loadPages, loadFacets, loadHistory, toast]);

  useEffect(() => {
    loadBackend();
  }, [loadBackend]);

  useEffect(() => {
    if (!connected || settingsLoadedRef.current) return;
    (async () => {
      try {
        const res = await authedApi(`/me/settings`, { method: "GET" });
        const settings = res?.settings || {};
        Object.entries(settings).forEach(([k, v]) => setTweak(k, v));
      } catch {}
      settingsLoadedRef.current = true;
    })();
  }, [connected, authedApi, setTweak]);

  useEffect(() => {
    if (!connected || !settingsLoadedRef.current) return;
    const t = setTimeout(() => {
      authedApi(`/me/settings`, { method: "POST", body: JSON.stringify({ settings: tv }) }).catch(() => {});
    }, 700);
    return () => clearTimeout(t);
  }, [connected, tv, authedApi]);

  useEffect(() => {
    if (!connected) return;
    loadPages();
  }, [connected, loadPages]);

  useEffect(() => {
    if (!connected) return;
    if (window.EventSource && authToken) return;
    const hasLive = jobs.some(j => j.state === "running" || j.state === "queued");
    if (!hasLive) return;
    const t = setInterval(async () => {
      const calls = [loadJobs(), loadPages(), loadFacets(), loadHistory()];
      if (role === "admin") calls.push(loadAdminSystem());
      await Promise.all(calls).catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [connected, authToken, jobs, role, loadJobs, loadPages, loadFacets, loadHistory, loadAdminSystem]);

  useEffect(() => {
    if (!connected || !authToken || !window.EventSource) return;
    const es = new EventSource(`${API_BASE}/jobs-sse?token=${encodeURIComponent(authToken)}`);
    const onJobs = (evt) => {
      try {
        const payload = JSON.parse(evt.data || "{}");
        if (Array.isArray(payload.jobs)) {
          setJobs(payload.jobs.map(mapJob));
          loadPages().catch(() => {});
          loadFacets().catch(() => {});
          loadHistory().catch(() => {});
          if (role === "admin") loadAdminSystem().catch(() => {});
        }
      } catch {}
    };
    es.addEventListener("jobs", onJobs);
    es.onerror = () => es.close();
    return () => {
      es.removeEventListener("jobs", onJobs);
      es.close();
    };
  }, [connected, authToken, role, loadPages, loadFacets, loadHistory, loadAdminSystem]);

  // Run an operation ------------------------------------------------
  const runAction = useCallback(async (action, value) => {
    if (action === "focus_add") {
      setOpsOpen(true);
      toast("Focus the Add URL field in the Operations console.", "info");
      return;
    }

    if (!connected) {
      toast("Backend not connected. Start API server first.", "err");
      return;
    }

    const map = {
      add_url: ["/actions/add-url", { url: value }],
      only_title: ["/actions/mirror-one", { title: value }],
      only_url: ["/actions/mirror-by-url", { url: value }],
      refresh_one: ["/actions/refresh-one", { title: value }],
      refresh_all: ["/actions/refresh-all", {}],
    };
    const entry = map[action];
    if (!entry) {
      toast(`Unknown action: ${action}`, "err");
      return;
    }

    try {
      const [path, body] = entry;
      const res = await authedApi(path, { method: "POST", body: JSON.stringify(body) });
      toast(`Queued job #${res.job_id}: ${action}`, "info");
      await Promise.all([loadJobs(), loadAdminSystem()]);
      setTimeout(() => {
        const calls = [loadJobs(), loadPages(), loadFacets(), loadHistory()];
        if (role === "admin") calls.push(loadAdminSystem());
        Promise.all(calls).catch(() => {});
      }, 1800);
    } catch (err) {
      toast(`Action failed: ${err.message}`, "err");
    }
  }, [connected, role, authedApi, loadJobs, loadPages, loadFacets, loadHistory, loadAdminSystem, toast]);

  // Keyboard: ⌘K for palette --------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(o => !o);
      } else if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && !paletteOpen) {
        e.preventDefault();
        document.getElementById("searchInput")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen]);

  useEffect(() => {
    if (!opened || filtered.length === 0) return;
    const onArrow = (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      if (document.activeElement?.tagName === "INPUT" || document.activeElement?.tagName === "TEXTAREA") return;
      const idx = filtered.findIndex((p) => p.slug === opened);
      if (idx < 0) return;
      if (e.key === "ArrowDown" && idx < filtered.length - 1) {
        e.preventDefault();
        setOpened(filtered[idx + 1].slug);
      }
      if (e.key === "ArrowUp" && idx > 0) {
        e.preventDefault();
        setOpened(filtered[idx - 1].slug);
      }
    };
    window.addEventListener("keydown", onArrow);
    return () => window.removeEventListener("keydown", onArrow);
  }, [opened, filtered]);

  // Dismiss toast
  const dismissToast = useCallback((id) => setToasts(t => t.filter(x => x.id !== id)), []);

  // Apply saved filter
  const applySaved = (sv) => {
    setColl(sv.collection);
    setStatus(sv.status);
    if (sv.source) setSrc(sv.source); else setSrc("any");
    if (sv.q) setQuery(sv.q); else setQuery("");
    if (Array.isArray(sv.tags) && sv.tags.length) setTags(new Set(sv.tags)); else setTags(new Set());
    toast(`Filter applied: ${sv.name}`, "info");
  };

  const saveCurrentFilter = useCallback(async () => {
    const name = window.prompt("Name this filter:", `Filter ${new Date().toLocaleTimeString()}`);
    if (!name) return;
    const queryObj = {
      collection,
      status,
      source: sourceType,
      q: query,
      tags: [...activeTags],
    };

    if (!connected) {
      const local = { id: `local-${Date.now()}`, name, collection, status };
      setSaved(s => [local, ...s]);
      toast("Saved locally (backend offline)", "warn");
      return;
    }

    try {
      await authedApi(`/saved-filters`, { method: "POST", body: JSON.stringify({ name, query: queryObj }) });
      await loadSavedFilters();
      toast(`Saved filter: ${name}`, "info");
    } catch (err) {
      toast(`Save failed: ${err.message}`, "err");
    }
  }, [collection, status, sourceType, query, activeTags, connected, authedApi, loadSavedFilters, toast]);

  // Toggle tag
  const toggleTag = (t) => {
    const s = new Set(activeTags);
    s.has(t) ? s.delete(t) : s.add(t);
    setTags(s);
  };

  // Render --------------------------------------------------------
  const totalSize = pages.reduce((a, p) => a + (p.size_bytes || 0), 0);
  const openedPage = detailItem || pages.find(p => p.slug === opened);

  const handleLogin = useCallback((token, nextRole, nextActor, nextEmail) => {
    localStorage.setItem("archive_token", token);
    localStorage.setItem("archive_role", nextRole || "viewer");
    localStorage.setItem("archive_user", nextActor || "frontend-user");
    if (nextEmail) { localStorage.setItem("profile_email", nextEmail); setUserEmail(nextEmail); }
    setAuthToken(token);
    setRole(nextRole || "viewer");
    setActor(nextActor || "frontend-user");
    setConnected(true);
    settingsLoadedRef.current = false;
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      if (authToken) await api(`/auth/logout`, { method: "POST" }, authToken);
    } catch {}
    localStorage.removeItem("archive_token");
    localStorage.removeItem("archive_role");
    localStorage.removeItem("archive_user");
    localStorage.removeItem("archive_auth_source");
    setAuthToken("");
    setConnected(false);
    setRole("viewer");
    setActor("frontend-user");
    setAuthSource("");
    settingsLoadedRef.current = false;
  }, [authToken]);

  // Only close the sidebar when it's a mobile drawer, not the persistent tablet sidebar
  const closeMobileSidebar = useCallback(() => {
    if (typeof window !== "undefined" && window.innerWidth <= 780) {
      setSidebarOpen(false);
    }
  }, []);

  const openOpsTab = useCallback((tabName) => {
    setMainTab("library");
    setOpsOpen(true);
    setOpsTab(tabName);
  }, []);

  if (!authToken) {
    return <SignInComponent onLogin={handleLogin} apiBase={API_BASE} />;
  }

  return (
    <>
        {/* Top bar */}
      <header className="topbar">
        {mainTab === "library" && (
          <button className="btn sm menu-toggle" aria-label="Toggle sidebar" onClick={() => setSidebarOpen(o => !o)}>
            <Icon d="M3 6h18M3 12h18M3 18h18" />
          </button>
        )}
        {mainTab === "admin" && (
          <button className="btn sm menu-toggle" aria-label="Back to library" title="Back to library" onClick={() => setMainTab("library")}>
            <Icon d="M15 18l-6-6 6-6M9 12h12" />
          </button>
        )}
        <div className="brand">
          <img src="logo.png" alt="logo" style={{height:28,width:"auto",objectFit:"contain",flexShrink:0}} onError={(e)=>{e.target.style.display="none"}} />
          <span className="brand-name">Archive<em> · Local Mirror Library</em></span>
        </div>
        <nav className="topnav" style={{display:"flex", gap:6, marginLeft:10}}>
          <button className={`btn sm hide-tablet${mainTab === "library" ? " primary" : ""}`} onClick={() => { setMainTab("library"); closeMobileSidebar(); }}>Library</button>
          <button className="btn sm hide-tablet" onClick={() => { openOpsTab("jobs"); closeMobileSidebar(); }}>Jobs</button>
          <button className="btn sm hide-sm hide-tablet" onClick={() => { openOpsTab("history"); closeMobileSidebar(); }}>History</button>
          {role === "admin" && <button className={`btn sm${mainTab === "admin" ? " primary" : ""}`} onClick={() => { setMainTab("admin"); setOpsOpen(false); closeMobileSidebar(); }}>Admin</button>}
        </nav>
        <button className="cmd-btn topbar-search" onClick={() => setPaletteOpen(true)}>
          <span className="left"><Icon d={IC.search} /><span className="cmd-label">Jump to page, action…</span></span>
          <span className="kbd">⌘K</span>
        </button>
        <span className="topbar-spacer hide-tablet" />
        {!opsOpen && (
          <button className="btn hide-sm" onClick={() => setOpsOpen(true)}>
            <Icon d={IC.terminal} /> <span className="btn-label">Operations</span>
          </button>
        )}
        {connected && role === "admin" && adminSystem && (
          <span className="role-pill hide-sm" title="API/worker status">
            <span className="role-dot" style={{background: adminSystem.worker_running ? "var(--ok)" : "var(--err)"}} />
            {adminSystem.jobs?.queued || 0}q/{adminSystem.jobs?.running || 0}r
          </span>
        )}
        <div style={{position:"relative"}}>
          <button className="profile-trigger" onClick={() => setProfileOpen(o => !o)} aria-haspopup="menu" aria-expanded={profileOpen} title="Account and preferences">
            {avatarUrl
              ? <img className="profile-trigger-avatar" src={avatarUrl} alt="" />
              : <span className="profile-trigger-avatar initials">{(actor || "?").slice(0,2).toUpperCase()}</span>
            }
            <span className="profile-trigger-text">
              <span className="profile-trigger-name">{actor}</span>
              <span className="profile-trigger-role">{role}</span>
            </span>
            <span className="profile-trigger-caret" aria-hidden="true">▾</span>
          </button>
          {profileOpen && (<>
            <div className="profile-scrim" onClick={() => setProfileOpen(false)} />
            <div className="profile-menu" role="menu">
              <div className="profile-head">
                <button className="profile-avatar-btn" onClick={() => avatarInputRef.current?.click()} title="Change profile picture">
                  {avatarUrl
                    ? <img src={avatarUrl} alt="" className="profile-avatar-img" />
                    : <span className="profile-avatar initials-lg">{(actor || "?").slice(0,2).toUpperCase()}</span>
                  }
                  <span className="profile-avatar-edit">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
                      <circle cx="12" cy="13" r="4"/>
                    </svg>
                  </span>
                </button>
                <input ref={avatarInputRef} type="file" accept="image/*" style={{display:"none"}}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    if (file.size > 2_000_000) { toast("Image too large (max 2 MB)", "warn"); return; }
                    const reader = new FileReader();
                    reader.onload = (ev) => {
                      const url = ev.target?.result;
                      if (typeof url === "string") {
                        try { localStorage.setItem("profile_avatar", url); setAvatarUrl(url); toast("Profile picture updated", "info"); }
                        catch { toast("Image too large to store locally.", "warn"); }
                      }
                    };
                    reader.readAsDataURL(file);
                    e.target.value = "";
                  }} />
                <div style={{minWidth:0, flex:1}}>
                  <div className="profile-name">{actor}</div>
                  <div className="profile-role-line">
                    <span className="profile-role-chip">{role}</span>
                    {authSource && <span className="profile-meta">{authSource}</span>}
                  </div>
                  <div className="profile-email" title={userEmail || "No email on file"}>
                    {userEmail || <span style={{color:"var(--ink-faint)",fontStyle:"italic"}}>no email on file</span>}
                  </div>
                </div>
              </div>
              {avatarUrl && (
                <button className="profile-row" onClick={() => { localStorage.removeItem("profile_avatar"); setAvatarUrl(""); toast("Profile picture removed", "info"); }}>
                  <span style={{color:"var(--err)"}}>Remove profile picture</span>
                </button>
              )}
              <div className="profile-section-label">Appearance</div>
              <div className="profile-segment" role="radiogroup" aria-label="Theme mode">
                {[
                  {key:"light",  label:"Light",  icon:"M12 3v1 M12 20v1 M4.2 4.2l.7.7 M19.1 19.1l.7.7 M3 12h1 M20 12h1 M4.2 19.8l.7-.7 M19.1 4.9l.7-.7 M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"},
                  {key:"dark",   label:"Dark",   icon:"M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"},
                  {key:"system", label:"System", icon:"M3 5h18v12H3z M9 21h6 M12 17v4"},
                ].map(t => (
                  <button key={t.key} className={`segment-btn${themeMode === t.key ? " on" : ""}`}
                    onClick={() => { setThemeMode(t.key); localStorage.setItem("theme_mode", t.key); }}
                    role="radio" aria-checked={themeMode === t.key}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                      <path d={t.icon} />
                    </svg>
                    {t.label}
                  </button>
                ))}
              </div>
              <button className="profile-row" onClick={() => setTweak("density", tv.density === "comfortable" ? "compact" : "comfortable")}>
                <span>Density</span><span className="profile-row-val">{tv.density}</span>
              </button>
              <button className="profile-row" onClick={() => setTweak("defaultView", tv.defaultView === "grid" ? "list" : "grid")}>
                <span>Default view</span><span className="profile-row-val">{tv.defaultView}</span>
              </button>
              <div className="profile-divider" />
              <button className="profile-row signout" onClick={() => { setProfileOpen(false); handleLogout(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9"/>
                </svg>
                <span>Sign out</span>
              </button>
            </div>
          </>)}
        </div>
      </header>

      {apiOffline && (
        <div style={{padding:"8px 14px", background:"var(--warn-bg)", borderBottom:"1px solid var(--line)", color:"var(--warn)", fontSize:12, display:"flex", alignItems:"center", gap:10}}>
          <Icon d={IC.warn} size={14} />
          <span style={{flex:1}}>API is unreachable — some actions may fail until connectivity returns.</span>
          <button className="btn sm" onClick={() => { setApiOffline(false); loadPages(); loadFacets(); }}
            style={{fontSize:11, padding:"2px 8px"}}>
            Retry
          </button>
        </div>
      )}

      {mainTab === "admin" ? (
        <AdminPanelComponent
          role={role}
          connected={connected}
          users={adminUsers}
          adminSystem={adminSystem}
          adminLogs={adminLogs}
          onCreateLocalUser={createLocalUser}
          onUpdateUser={upsertAdminUser}
          onResetPassword={resetAdminPassword}
          onDeleteUser={deleteAdminUser}
          onIssueApiKey={issueAdminApiKey}
          onRefresh={refreshAdminPanel}
          onAdminSync={runAdminSync}
          onAdminCleanup={runAdminCleanup}
          onRefreshLogs={loadAdminLogs}
        />
      ) : null}

      <div className={`layout${opsOpen ? "" : " ops-collapsed"}${mainTab === "admin" ? " hidden" : ""}${!sidebarOpen && mainTab === "library" ? " sidebar-hidden" : ""}`}>

        {/* Mobile sidebar scrim */}
        {mainTab === "library" && sidebarOpen && <div className="sidebar-scrim" onClick={() => setSidebarOpen(false)} />}

        {/* Sidebar */}
        {mainTab === "library" && <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
          <div className="side-group">
            <div className="side-label">Collections <span className="hint">{pages.length}</span></div>
            <button className={`facet-row${collection === "all" ? " active" : ""}`} onClick={() => setColl("all")}>
              <span>All collections</span><span className="facet-count">{pages.length}</span>
            </button>
            {[...collectionCounts.entries()].sort().map(([name, n]) => (
              <button key={name}
                className={`facet-row${collection === name ? " active" : ""}`}
                onClick={() => setColl(name)}>
                <span>{name}</span><span className="facet-count">{n}</span>
              </button>
            ))}
          </div>

          <div className="side-group">
            <div className="side-label">Status</div>
            {["any","fresh","stale","queued","failed"].map(s => (
              <button key={s}
                className={`facet-row${status === s ? " active" : ""}`}
                onClick={() => setStatus(s)}>
                <span style={{textTransform:"capitalize"}}>{s === "any" ? "Any status" : s}</span>
                <span className="facet-count">{s === "any" ? pages.length : (statusCounts[s] || 0)}</span>
              </button>
            ))}
          </div>

          <div className="side-group">
            <div className="side-label">Source</div>
            {["any", ...sourceCounts.keys()].map(s => (
              <button key={s}
                className={`facet-row${sourceType === s ? " active" : ""}`}
                onClick={() => setSrc(s)}>
                <span style={{textTransform:"capitalize"}}>{s === "any" ? "Any source" : s}</span>
                <span className="facet-count">{s === "any" ? pages.length : (sourceCounts.get(s) || 0)}</span>
              </button>
            ))}
          </div>

          <div className="side-group">
            <div className="side-label">Tags</div>
            <div style={{display:"flex",flexWrap:"wrap",gap:4}}>
              {tagCounts.slice(0, 12).map(([t, n]) => (
                <button key={t}
                  onClick={() => toggleTag(t)}
                  className="chip tag"
                  style={{
                    cursor:"pointer",
                    background: activeTags.has(t) ? "var(--accent-soft)" : "transparent",
                    borderColor: activeTags.has(t) ? "var(--accent)" : "var(--line-soft)",
                    color: activeTags.has(t) ? "var(--accent-ink)" : "var(--ink-faint)",
                  }}>
                  #{t} <span style={{opacity:.6}}>{n}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="side-group">
            <div className="side-label">
              Saved filters
              <button className="btn ghost sm" title="New filter"><Icon d={IC.plus} /></button>
            </div>
            {saved.map(sv => (
              <button key={sv.id} className="saved-filter" onClick={() => applySaved(sv)}>
                <span><Icon d={IC.star} size={12} /> {sv.name}</span>
                <span className="qty">{pages.filter(p =>
                  (sv.collection === "all" || p.collection === sv.collection) &&
                  (sv.status === "any" || p.status === sv.status)
                ).length}</span>
              </button>
            ))}
          </div>

          {/* Profile footer — only visible in mobile sidebar */}
          <div className="sidebar-profile-footer">
            <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:12}}>
              {avatarUrl
                ? <img src={avatarUrl} alt="" style={{width:36,height:36,borderRadius:"50%",objectFit:"cover",flexShrink:0}} />
                : <span style={{width:36,height:36,borderRadius:"50%",background:"linear-gradient(135deg,var(--accent),oklch(0.35 0.09 210))",display:"grid",placeItems:"center",color:"var(--paper-0)",font:"600 13px/1 var(--f-mono)",flexShrink:0}}>{(actor||"?").slice(0,2).toUpperCase()}</span>
              }
              <div style={{minWidth:0,flex:1}}>
                <div style={{font:"500 13px/1.2 var(--f-sans)",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",color:"var(--ink)"}}>{actor}</div>
                <div style={{font:"400 10px/1 var(--f-mono)",color:"var(--ink-faint)",textTransform:"uppercase",letterSpacing:"0.06em",marginTop:2}}>{role}{authSource ? ` · ${authSource}` : ""}</div>
                {userEmail && <div style={{font:"400 11px/1.3 var(--f-sans)",color:"var(--ink-soft)",marginTop:2,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{userEmail}</div>}
              </div>
            </div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap",marginBottom:10}}>
              {["light","dark","system"].map(t => (
                <button key={t} onClick={() => { setThemeMode(t); localStorage.setItem("theme_mode", t); }}
                  style={{flex:1,padding:"5px 4px",borderRadius:6,border:`1px solid ${themeMode===t?"var(--accent)":"var(--line)"}`,background:themeMode===t?"var(--accent-soft)":"transparent",color:themeMode===t?"var(--accent-ink)":"var(--ink-soft)",font:"500 11px/1 var(--f-sans)",cursor:"pointer",textTransform:"capitalize"}}>
                  {t}
                </button>
              ))}
            </div>
            <button className="btn" style={{width:"100%",color:"var(--err)",borderColor:"var(--err-bg)",background:"var(--err-bg)"}}
              onClick={() => { setSidebarOpen(false); handleLogout(); }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{marginRight:5}}>
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9"/>
              </svg>
              Sign out
            </button>
          </div>
        </aside>}

        {/* Main */}
        <main className="main">
          <section className="hero">
            <div>
              <h1>Local Mirror Library</h1>
              <p className="lede">
                A metadata-first index of every page you've pinned. Search, filter across
                collections &amp; tags, and trigger mirror operations from the console on the right.
              </p>
            </div>
            <div className="hero-stats">
              <div className="stat"><div className="stat-n">{pages.length}</div><div className="stat-l">Pages</div></div>
              <div className="stat"><div className="stat-n">{collectionCounts.size}</div><div className="stat-l">Collections</div></div>
              <div className="stat"><div className="stat-n">{fmtBytes(totalSize)}</div><div className="stat-l">On disk</div></div>
              <div className="stat"><div className="stat-n" style={{color: statusCounts.stale ? "var(--warn)" : "var(--ok)"}}>
                {statusCounts.stale}</div><div className="stat-l">Stale</div></div>
            </div>
          </section>

          {tv.showFilterBar && (
            <div className="filterbar">
              <div className="search-field">
                <Icon d={IC.search} />
                <input id="searchInput" placeholder="Search title, oldid, host, tag… ( / to focus )"
                       value={query} onChange={(e) => setQuery(e.target.value)} />
                <span className="kbd">/</span>
              </div>
              <select className="facet-chip" value={sort} onChange={(e) => setSort(e.target.value)}
                      style={{appearance:"none"}}>
                <option value="archived_desc">Newest archived</option>
                <option value="archived_asc">Oldest archived</option>
                <option value="title_asc">Title A→Z</option>
                <option value="size_desc">Largest</option>
              </select>
              <button className={`facet-chip${status === "stale" ? " active" : ""}`}
                onClick={() => setStatus(status === "stale" ? "any" : "stale")}>
                Stale <span className="cnt">{statusCounts.stale}</span>
              </button>
              <button className={`facet-chip${status === "failed" ? " active" : ""}`}
                onClick={() => setStatus(status === "failed" ? "any" : "failed")}>
                Failed <span className="cnt">{statusCounts.failed}</span>
              </button>
              <div className="seg" role="tablist" aria-label="View mode">
                <button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")} title="Grid">
                  <Icon d={IC.grid} />
                </button>
                <button className={view === "list" ? "on" : ""} onClick={() => setView("list")} title="List">
                  <Icon d={IC.list} />
                </button>
              </div>
            </div>
          )}

          <div className="active-filters">
            {activeFilters.length === 0
              ? <span style={{color:"var(--ink-faint)", fontSize:12}}>No filters applied</span>
              : activeFilters.map((f, i) => (
                  <span key={i} className="tag">
                    <span className="key">{f.key}:</span>{f.val}
                    <button onClick={f.clear} aria-label={`Remove ${f.key} filter`}>×</button>
                  </span>
                ))
            }
            {activeFilters.length > 0 && (
              <button className="save" onClick={saveCurrentFilter}>
                <Icon d={IC.star} size={11}/> Save as filter
              </button>
            )}
          </div>

          <div className="result-meta">
            <div className="count">
              <strong>{filtered.length}</strong> of {pages.length} pages
              {activeFilters.length > 0 && <span style={{color:"var(--ink-faint)"}}> · {activeFilters.length} filter{activeFilters.length > 1 ? "s" : ""}</span>}
            </div>
            <div style={{display:"flex",gap:12,alignItems:"center"}}>
              <span style={{color:"var(--ink-faint)"}}>
                Updated {fmtAgo(pages[0]?.archived_at_utc)}
              </span>
              <button className="btn sm" onClick={() => runAction("refresh_all", "")}>
                <Icon d={IC.refresh} /> Refresh all
              </button>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="empty">
              <svg width="56" height="56" viewBox="0 0 56 56" fill="none" style={{opacity:0.25}}>
                <rect x="8" y="14" width="40" height="30" rx="4" stroke="currentColor" strokeWidth="2" fill="none"/>
                <line x1="8" y1="22" x2="48" y2="22" stroke="currentColor" strokeWidth="2"/>
                <line x1="16" y1="30" x2="32" y2="30" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                <line x1="16" y1="36" x2="26" y2="36" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                <circle cx="42" cy="38" r="8" fill="var(--paper)" stroke="currentColor" strokeWidth="2"/>
                <line x1="39" y1="38" x2="45" y2="38" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
              <h3 style={{margin:"10px 0 4px"}}>Nothing matches</h3>
              <p style={{margin:0}}>Clear filters, try a different search, or mirror a new URL.</p>
            </div>
          ) : view === "grid" ? (
            <div className="grid">
              {filtered.map(p => (
                <Card key={p.slug} page={p}
                  selected={opened === p.slug}
                  onOpen={() => setOpened(p.slug)} />
              ))}
            </div>
          ) : (
            <div className="list">
              <div className="list-row head">
                <div>Title</div><div>Status</div><div>Collection</div>
                <div>Oldid</div><div>Archived</div><div>Size</div>
              </div>
              {filtered.map(p => (
                <ListRow key={p.slug} page={p} onOpen={() => setOpened(p.slug)} />
              ))}
            </div>
          )}
        </main>

        {/* Operations console */}
        {!opsOpen && mainTab !== "admin" && !opened && (
          <button className="ops-fab" aria-label="Open operations console" title="Operations" onClick={() => setOpsOpen(true)}>
            <Icon d={IC.terminal} />
          </button>
        )}
        {opsOpen && <div className="ops-scrim" onClick={() => setOpsOpen(false)} />}
        {opsOpen && (
          <Ops
            jobs={jobs}
            historyRows={historyRows}
            onRun={runAction}
            role={role}
            connected={connected}
            adminUsers={adminUsers}
            onUpsertUser={upsertAdminUser}
            onDeleteUser={deleteAdminUser}
            onIssueUserApiKey={issueAdminApiKey}
            onChangeOwnPassword={changeOwnPassword}
            onResetUserPassword={resetAdminPassword}
            onRetryJob={retryJob}
            onCancelJob={cancelJob}
            onGetJobDetail={getJobDetail}
            adminSystem={adminSystem}
            onRefreshAdminSystem={refreshAdminSystem}
            onAdminSync={runAdminSync}
            onAdminCleanup={runAdminCleanup}
            onExportHistoryCsv={exportHistoryCsv}
            onRetryAllFailedJobs={retryAllFailedJobs}
            adminLogs={adminLogs}
            onRefreshAdminLogs={loadAdminLogs}
            authSource={authSource}
            activeTab={opsTab}
            onTabChange={setOpsTab}
            onClose={() => setOpsOpen(false)}
          />
        )}
      </div>

      {/* Drawer */}
      <Drawer page={openedPage} onClose={() => setOpened(null)} onRun={runAction} role={role} onAddTag={addItemTag} onRemoveTag={removeItemTag} onDeleteItem={deleteItem} tagSuggestions={knownTags} />

      {/* Palette */}
      <Palette open={paletteOpen} onClose={() => setPaletteOpen(false)}
        pages={pages} onPick={(p) => setOpened(p.slug)} onAction={runAction} />

      {/* Toasts */}
      <Toasts toasts={toasts} dismiss={dismissToast} />

      {/* Tweaks */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="Layout">
          <TweakRadio label="Default view" value={tv.defaultView}
            options={[{value:"grid",label:"Grid"},{value:"list",label:"List"}]}
            onChange={(v) => setTweak("defaultView", v)} />
          <TweakToggle label="Show Operations console" value={tv.showOpsByDefault}
            onChange={(v) => setTweak("showOpsByDefault", v)} />
          <TweakToggle label="Show filter bar" value={tv.showFilterBar}
            onChange={(v) => setTweak("showFilterBar", v)} />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
