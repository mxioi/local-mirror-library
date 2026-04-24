/* global React, ReactDOM */
const { useState, useEffect, useMemo, useRef, useCallback } = React;

// ---------- tiny icon set (inline, minimal strokes) ----------
const Icon = ({ d, size = 14 }) => (
  <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6">
    <path d={d} />
  </svg>
);
const IC = {
  search:   "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.35-4.35",
  close:    "M6 6l12 12M18 6 6 18",
  plus:     "M12 5v14M5 12h14",
  refresh:  "M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.3L3 16M3 21v-5h5",
  external: "M7 17 17 7M8 7h9v9",
  grid:     "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  list:     "M4 6h16M4 12h16M4 18h16",
  filter:   "M3 5h18l-7 9v6l-4-2v-4Z",
  download: "M12 4v12m0 0 4-4m-4 4-4-4M4 20h16",
  trash:    "M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-7 0v13a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V7",
  star:     "M12 3l2.9 5.9 6.6.9-4.8 4.6 1.2 6.5L12 18l-5.9 2.9L7.3 14.4 2.5 9.8l6.6-.9L12 3Z",
  play:     "M6 4l14 8-14 8V4Z",
  terminal: "M4 6l5 6-5 6M13 18h7",
  lock:     "M6 10V8a6 6 0 1 1 12 0v2M5 10h14v10H5z",
  chevron:  "M9 6l6 6-6 6",
  history:  "M12 8v4l3 2M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5",
  tag:      "M20 12 12 4H4v8l8 8 8-8Z M8 8h.01",
};

// ---------- helpers ----------
const hostOf = (u) => { try { return new URL(u).host; } catch { return ""; } };
const fmtBytes = (n) => {
  if (!n) return "—";
  const u = ["B","KB","MB","GB"]; let i = 0; while (n >= 1024 && i < u.length-1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 ? 1 : 0)} ${u[i]}`;
};
const fmtAgo = (iso) => {
  if (!iso) return "never";
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso;
  const secs = Math.floor((Date.now() - d.getTime())/1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs/60)}m ago`;
  if (secs < 86_400) return `${Math.floor(secs/3600)}h ago`;
  return `${Math.floor(secs/86_400)}d ago`;
};
const fmtFull = (iso) => { if (!iso) return "—"; const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(); };
const fmtDur = (ms) => !ms ? "—" : ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`;
const initials = (s) => s.split(/[._\s-]/).filter(Boolean).slice(0,2).map(x => x[0].toUpperCase()).join("");

const SOURCE_LABEL = { wikipedia: "W", rfc: "R", pdf: "P", html: "H" };

// ---------- status badge ----------
function StatusBadge({ status }) {
  const label = { fresh: "fresh", stale: "stale", queued: "queued", failed: "failed", running: "running" }[status] || status;
  return (
    <span className={`status-badge status-${status}`}>
      <span className="dot" />{label}
    </span>
  );
}

// ---------- card ----------
function Card({ page, selected, onOpen }) {
  return (
    <article
      className={`card${selected ? " selected" : ""}`}
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
      aria-label={`Open detail for ${page.title}`}
    >
      <div className="card-top">
        <h3>{page.title}</h3>
        <div className={`source-dot ${page.source_type}`} title={page.source_type}>
          {SOURCE_LABEL[page.source_type] || "?"}
        </div>
      </div>
      <div className="card-chips">
        <StatusBadge status={page.status} />
        <span className="chip">{page.collection}</span>
        {page.oldid && <span className="chip oldid"><span className="k">oldid</span> {page.oldid.slice(0,6)}…</span>}
      </div>
      <div className="card-chips" style={{marginTop: "-2px"}}>
        {page.tags.slice(0, 3).map(t => <span key={t} className="chip tag">#{t}</span>)}
      </div>
      <div className="card-foot">
        <span className="owner">
          <span className="avatar">{initials(page.owner)}</span>
          <span>{page.owner}</span>
        </span>
        <span title={fmtFull(page.archived_at_utc)}>{fmtAgo(page.archived_at_utc)} · {fmtBytes(page.size_bytes)}</span>
      </div>
    </article>
  );
}

// ---------- list row ----------
function ListRow({ page, onOpen }) {
  return (
    <div className="list-row" onClick={onOpen} role="button" tabIndex={0}
         onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}>
      <div className="t">{page.title}</div>
      <div><StatusBadge status={page.status} /></div>
      <div className="mono">{page.collection}</div>
      <div className="mono">{page.oldid ? page.oldid.slice(0,8) + "…" : "—"}</div>
      <div className="mono" title={fmtFull(page.archived_at_utc)}>{fmtAgo(page.archived_at_utc)}</div>
      <div className="mono">{fmtBytes(page.size_bytes)}</div>
    </div>
  );
}

window.LibraryPrimitives = { Icon, IC, Card, ListRow, StatusBadge, hostOf, fmtBytes, fmtAgo, fmtFull, fmtDur, initials };
