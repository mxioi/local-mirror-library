/* global React, LibraryPrimitives */
const { useState, useEffect, useMemo, useRef } = React;
const { Icon, IC, StatusBadge, hostOf, fmtBytes, fmtAgo, fmtFull, fmtDur, initials } = window.LibraryPrimitives;

// ---------- detail drawer ----------
function Drawer({ page, onClose, onRun, role, onAddTag, onRemoveTag, onDeleteItem, tagSuggestions }) {
  const [timelineIdx, setTimelineIdx] = useState(0);
  const [tagInput, setTagInput] = useState("");

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!page?.timeline || page.timeline.length === 0) {
      setTimelineIdx(0);
      return;
    }
    const idx = page.timeline.findIndex((t) => t.is_current);
    setTimelineIdx(idx >= 0 ? idx : 0);
  }, [page?.slug, page?.timeline]);

  const canEdit = role !== "viewer";
  const timeline = page?.timeline || [];
  const selectedSnapshot = timeline[timelineIdx] || null;

  return (
    <>
      <div className={`drawer-scrim${page ? " open" : ""}`} onClick={onClose} />
      <aside className={`drawer${page ? " open" : ""}`} aria-hidden={!page}>
        {page && (
          <>
            <div className="drawer-head">
              <div style={{minWidth: 0, flex: 1}}>
                <div className="sub">{page.source_type.toUpperCase()} · {page.host}</div>
                <h2>{page.title}</h2>
                <div className="card-chips" style={{marginTop: 8}}>
                  <StatusBadge status={page.status} />
                  <span className="chip">{page.collection}</span>
                  {page.tags.map(t => (
                    <span key={t} className="chip tag" style={{display:"inline-flex", gap:4, alignItems:"center"}}>
                      #{t}
                      {canEdit && page?.id && <button onClick={(e) => { e.stopPropagation(); onRemoveTag?.(page.id, t); }} style={{all:"unset", cursor:"pointer", color:"var(--ink-faint)"}}>×</button>}
                    </span>
                  ))}
                </div>
                {canEdit && page?.id && (
                  <div style={{display:"flex", gap:6, marginTop:8}}>
                    <input value={tagInput} onChange={(e)=>setTagInput(e.target.value)} placeholder="Add tag" style={{maxWidth:220}} list="tag-suggestions" />
                    <button className="btn sm" disabled={!tagInput.trim()} onClick={() => { onAddTag?.(page.id, tagInput.trim()); setTagInput(""); }}>
                      <Icon d={IC.plus} /> Tag
                    </button>
                  </div>
                )}
                <datalist id="tag-suggestions">
                  {(tagSuggestions || []).map((t) => <option key={t} value={t} />)}
                </datalist>
              </div>
              <button className="drawer-close" onClick={onClose} aria-label="Close detail">
                <Icon d={IC.close} />
              </button>
            </div>

            <div className="drawer-body">
              <h4 className="section-title">Archive metadata</h4>
              <dl className="meta-grid">
                <dt>oldid</dt>             <dd><code>{page.oldid || "— (latest pin not set)"}</code></dd>
                <dt>Archived</dt>          <dd>{fmtFull(page.archived_at_utc)} <span style={{color:"var(--ink-faint)"}}>({fmtAgo(page.archived_at_utc)})</span></dd>
                <dt>Source URL</dt>        <dd><a href={page.source_url} target="_blank" rel="noopener" style={{color:"var(--accent-ink)"}}>{page.source_url}</a></dd>
                <dt>Checksum</dt>          <dd><code>{page.checksum || "—"}</code></dd>
                <dt>Size</dt>              <dd>{fmtBytes(page.size_bytes)}</dd>
                <dt>Retention</dt>         <dd>{page.retention}</dd>
                <dt>Owner</dt>             <dd>{page.owner}</dd>
                <dt>Changes since init</dt><dd>{page.change_count}</dd>
              </dl>

              <h4 className="section-title">Audit trail</h4>
              {page.audit && page.audit.length > 0 ? (
                <div>
                  {page.audit.slice(0, 8).map((a, idx) => (
                    <div key={idx} className="audit-row">
                      <span className="when">{fmtFull(a.created_at_utc)}</span>
                      <span className="by">{a.actor} · <strong style={{color:"var(--ink)"}}>{a.action}</strong></span>
                      <span className="result" style={{color: a.result === "ok" ? "var(--ok)" : "var(--err)"}}>{a.result}</span>
                    </div>
                  ))}
                </div>
              ) : page.last_run ? (
                <div>
                  <div className="audit-row">
                    <span className="when">{fmtFull(page.last_run.at)}</span>
                    <span className="by">by <strong style={{color:"var(--ink)"}}>{page.last_run.by}</strong> · {fmtDur(page.last_run.duration_ms)}</span>
                    <span className="result" style={{color: page.last_run.result === "ok" ? "var(--ok)" : "var(--err)"}}>
                      {page.last_run.result}
                    </span>
                  </div>
                  <div className="audit-row">
                    <span className="when">earlier</span>
                    <span className="by">Initial import</span>
                    <span className="result">ok</span>
                  </div>
                </div>
              ) : (
                <p style={{color:"var(--ink-faint)", fontSize: 13, margin: 0}}>No runs yet — queued for first mirror.</p>
              )}

              <h4 className="section-title">Snapshot timeline</h4>
              {page.timeline && page.timeline.length > 0 ? (
                <div>
                  <div style={{display:"grid", gap:8, marginBottom:10}}>
                    <div style={{display:"flex", gap:8, alignItems:"center"}}>
                      <button className="btn sm" onClick={() => setTimelineIdx((i) => Math.max(0, i - 1))} disabled={timelineIdx <= 0}>
                        Older
                      </button>
                      <input
                        type="range"
                        min="0"
                        max={Math.max(0, timeline.length - 1)}
                        value={timelineIdx}
                        onChange={(e) => setTimelineIdx(Number(e.target.value || 0))}
                        style={{flex:1}}
                      />
                      <button className="btn sm" onClick={() => setTimelineIdx((i) => Math.min(timeline.length - 1, i + 1))} disabled={timelineIdx >= timeline.length - 1}>
                        Newer
                      </button>
                    </div>

                    {selectedSnapshot && (
                      <div className="audit-row">
                        <span className="when">{fmtFull(selectedSnapshot.archived_at_utc)}</span>
                        <span className="by">
                          <strong style={{color:"var(--ink)"}}>{selectedSnapshot.oldid ? `oldid ${selectedSnapshot.oldid}` : "latest"}</strong>
                          <span style={{marginLeft:8,color:"var(--ink-faint)"}}>{fmtBytes(selectedSnapshot.file_size_bytes)}</span>
                        </span>
                        <span className="result">
                          {selectedSnapshot.is_current ? "current" : (
                            <a href={selectedSnapshot.local_href || "#"} style={{color:"var(--accent-ink)"}}>open</a>
                          )}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <p style={{color:"var(--ink-faint)", fontSize: 13, margin: 0}}>No additional snapshots yet.</p>
              )}
            </div>

            <div className="drawer-foot">
              <button className="btn primary" onClick={() => onRun("refresh_one", page.title)} disabled={!canEdit}>
                <Icon d={IC.refresh} /> Refresh &amp; mirror
              </button>
              <a className="btn" href={page.source_url} target="_blank" rel="noopener">
                <Icon d={IC.external} /> Open source
              </a>
              <a className="btn" href={page.local_href || "#local"}>
                <Icon d={IC.play} /> Open local
              </a>
              <span className="spacer" />
              <button className="btn danger" disabled={!canEdit || !page?.id} onClick={() => {
                const reason = window.prompt("Delete reason:", "No longer needed");
                if (!reason) return;
                onDeleteItem?.(page.id, reason);
              }}>
                <Icon d={IC.trash} /> Remove
              </button>
            </div>
          </>
        )}
      </aside>
    </>
  );
}

// ---------- operations console ----------
function Ops({ jobs, historyRows, onRun, role, connected, adminUsers, onUpsertUser, onDeleteUser, onIssueUserApiKey, onChangeOwnPassword, onResetUserPassword, onRetryJob, onCancelJob, onGetJobDetail, adminSystem, onRefreshAdminSystem, onAdminSync, onAdminCleanup, onExportHistoryCsv, onRetryAllFailedJobs, adminLogs, onRefreshAdminLogs, authSource, onClose, activeTab, onTabChange }) {
  const [tabState, setTabState] = useState("run");
  const tab = activeTab || tabState;
  const setTab = (next) => {
    if (onTabChange) onTabChange(next);
    else setTabState(next);
  };
  const canEdit = role !== "viewer";

  return (
    <section className="ops" aria-label="Operations console">
      <div className="ops-head">
        <h2>Operations</h2>
        <div className="hstack">
          <span className="mode">{role.toUpperCase()}</span>
          <button className="btn ghost sm" onClick={onClose} title="Hide console"><Icon d={IC.close} /></button>
        </div>
      </div>
      <div className="ops-tabs">
        <button className={tab === "run" ? "on" : ""} onClick={() => setTab("run")}>Run</button>
        <button className={tab === "jobs" ? "on" : ""} onClick={() => setTab("jobs")}>
          Jobs {jobs.filter(j => j.state === "running" || j.state === "queued").length > 0 &&
            <span style={{color:"var(--info)", marginLeft:4}}>●</span>}
        </button>
        <button className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>History</button>
      </div>
      <div className="ops-body">
        {tab === "run" && <RunTab onRun={onRun} canEdit={canEdit} role={role} connected={connected} adminUsers={adminUsers} onUpsertUser={onUpsertUser} onDeleteUser={onDeleteUser} onIssueUserApiKey={onIssueUserApiKey} onChangeOwnPassword={onChangeOwnPassword} onResetUserPassword={onResetUserPassword} authSource={authSource} adminSystem={adminSystem} onRefreshAdminSystem={onRefreshAdminSystem} onAdminSync={onAdminSync} onAdminCleanup={onAdminCleanup} adminLogs={adminLogs} onRefreshAdminLogs={onRefreshAdminLogs} />}
        {tab === "jobs" && <JobsTab jobs={jobs} canEdit={canEdit} onRetryJob={onRetryJob} onCancelJob={onCancelJob} onGetJobDetail={onGetJobDetail} onRetryAllFailedJobs={onRetryAllFailedJobs} />}
        {tab === "history" && <HistoryTab jobs={jobs} historyRows={historyRows} onExportHistoryCsv={onExportHistoryCsv} />}
      </div>
    </section>
  );
}

function OpBlock({ title, hint, children, locked }) {
  return (
    <div className={`op-block${locked ? " locked" : ""}`}>
      <div className="op-block-head">
        <h3>{title}</h3>
        {hint && !locked && <span className="hint">{hint}</span>}
      </div>
      <div className="op-block-body">{children}</div>
    </div>
  );
}

function RunTab({ onRun, canEdit, role, connected, adminUsers, onUpsertUser, onDeleteUser, onIssueUserApiKey, onChangeOwnPassword, onResetUserPassword, authSource, adminSystem, onRefreshAdminSystem, onAdminSync, onAdminCleanup, adminLogs, onRefreshAdminLogs }) {
  const [addUrl, setAddUrl] = useState("");
  const [onlyTitle, setOnlyTitle] = useState("");
  const [onlyUrl, setOnlyUrl] = useState("");
  const [refreshOne, setRefreshOne] = useState("");
  const [newUser, setNewUser] = useState("");
  const [newRole, setNewRole] = useState("viewer");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const go = (action, value, reset) => {
    if (!canEdit) return;
    onRun(action, value);
    reset && reset();
  };

  return (
    <div>
      {!canEdit && (
        <div style={{
          background: "var(--warn-bg)", color: "var(--warn)",
          border: "1px solid oklch(0.85 0.05 70)", borderRadius: 8,
          padding: "8px 12px", fontSize: 12, marginBottom: 12,
          display: "flex", gap: 8, alignItems: "center"
        }}>
          <Icon d={IC.lock} />
          <span>Viewer role — actions are disabled. Ask an admin for archive-operator access.</span>
        </div>
      )}

      <OpBlock title="Add URL + mirror" hint="POST /api/v1/actions/*" locked={!canEdit}>
        <div className="op-form">
          <div className="lbl">Source URL<span className="tip">wikipedia, rfc, pdf</span></div>
          <div className="row">
            <input
              value={addUrl} onChange={(e) => setAddUrl(e.target.value)}
              placeholder="https://en.wikipedia.org/wiki/…"
              disabled={!canEdit}
            />
            <button className="btn primary" disabled={!canEdit || !addUrl}
              onClick={() => go("add_url", addUrl, () => setAddUrl(""))}>
              <Icon d={IC.plus} /> Add
            </button>
          </div>
        </div>
      </OpBlock>

      <OpBlock title="Mirror by title" locked={!canEdit}>
        <div className="op-form">
          <div className="row">
            <input
              value={onlyTitle} onChange={(e) => setOnlyTitle(e.target.value)}
              placeholder="Domain_Name_System"
              disabled={!canEdit}
            />
            <button className="btn" disabled={!canEdit || !onlyTitle}
              onClick={() => go("only_title", onlyTitle, () => setOnlyTitle(""))}>Run</button>
          </div>
        </div>
      </OpBlock>

      <OpBlock title="Mirror by URL" locked={!canEdit}>
        <div className="op-form">
          <div className="row">
            <input value={onlyUrl} onChange={(e) => setOnlyUrl(e.target.value)}
              placeholder="https://en.wikipedia.org/wiki/IPv4" disabled={!canEdit} />
            <button className="btn" disabled={!canEdit || !onlyUrl}
              onClick={() => go("only_url", onlyUrl, () => setOnlyUrl(""))}>Run</button>
          </div>
        </div>
      </OpBlock>

      <OpBlock title="Refresh one" locked={!canEdit}>
        <div className="op-form">
          <div className="row">
            <input value={refreshOne} onChange={(e) => setRefreshOne(e.target.value)}
              placeholder="IPv4" disabled={!canEdit} />
            <button className="btn" disabled={!canEdit || !refreshOne}
              onClick={() => go("refresh_one", refreshOne, () => setRefreshOne(""))}>
              <Icon d={IC.refresh} /> Refresh
            </button>
          </div>
        </div>
      </OpBlock>

      <OpBlock title="Refresh all" hint="long job" locked={!canEdit || role === "operator"}>
        <div className="op-form" style={{margin: 0}}>
          <p style={{margin:"0 0 10px", color:"var(--ink-soft)", fontSize:13}}>
            Re-mirrors every pinned page. Streams as a batch job.
          </p>
          <button className="btn primary" disabled={!canEdit || role === "operator"} style={{width:"100%"}}
            onClick={() => go("refresh_all", "", null)}>
            <Icon d={IC.refresh} /> Run full update
          </button>
          {role === "operator" && (
            <p style={{fontSize:11, color:"var(--ink-faint)", marginTop:8}}>
              Bulk refresh reserved for admin role.
            </p>
          )}
        </div>
      </OpBlock>

      <OpBlock title="Account security" hint="local accounts" locked={!connected}>
        {!connected ? (
          <p style={{margin:0,color:"var(--ink-faint)",fontSize:12}}>Backend offline.</p>
        ) : authSource && authSource !== "local" ? (
          <p style={{margin:0,color:"var(--ink-faint)",fontSize:12}}>Password changes for your account are managed in Active Directory.</p>
        ) : (
          <div className="op-form" style={{margin: 0}}>
            <div className="lbl">Change your password<span className="tip">for local-auth users</span></div>
            <div className="row" style={{display:"grid", gap:8}}>
              <input value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} placeholder="current password" type="password" />
              <input value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="new password (min 8 chars)" type="password" />
              {newPassword && (() => {
                const len = newPassword.length;
                const hasUpper = /[A-Z]/.test(newPassword);
                const hasNum = /[0-9]/.test(newPassword);
                const hasSymbol = /[^A-Za-z0-9]/.test(newPassword);
                const score = (len >= 8 ? 1 : 0) + (len >= 12 ? 1 : 0) + (hasUpper ? 1 : 0) + (hasNum ? 1 : 0) + (hasSymbol ? 1 : 0);
                const label = score <= 1 ? "Weak" : score <= 3 ? "Fair" : score === 4 ? "Good" : "Strong";
                const color = score <= 1 ? "var(--err)" : score <= 3 ? "var(--warn)" : "var(--ok)";
                return (
                  <div style={{display:"grid", gap:3}}>
                    <div style={{display:"flex", gap:3}}>
                      {[1,2,3,4,5].map(i => (
                        <div key={i} style={{flex:1, height:3, borderRadius:2, background: i <= score ? color : "var(--line)", transition:"background 0.2s"}} />
                      ))}
                    </div>
                    <span style={{fontSize:11, color, textAlign:"right"}}>{label}</span>
                  </div>
                );
              })()}
              <button
                className="btn"
                disabled={!oldPassword || !newPassword || newPassword.length < 8}
                onClick={() => {
                  onChangeOwnPassword?.(oldPassword, newPassword);
                  setOldPassword("");
                  setNewPassword("");
                }}
              >
                Update password
              </button>
            </div>
          </div>
        )}
      </OpBlock>

    </div>
  );
}

function JobsTab({ jobs, canEdit, onRetryJob, onCancelJob, onGetJobDetail, onRetryAllFailedJobs }) {
  const live = jobs.filter(j => j.state === "running" || j.state === "queued");
  const done = jobs.filter(j => j.state === "complete" || j.state === "failed" || j.state === "cancelled").slice(0, 20);
  const [detail, setDetail] = useState(null);
  const [detailBusy, setDetailBusy] = useState(false);

  const openDetail = async (jobId) => {
    if (!jobId || !onGetJobDetail) return;
    setDetailBusy(true);
    const job = await onGetJobDetail(jobId);
    if (job) setDetail(job);
    setDetailBusy(false);
  };
  return (
    <div>
      <div style={{display:"flex", justifyContent:"flex-end", marginBottom:8}}>
        <button className="btn sm" disabled={!canEdit || !jobs.some(j => j.state === "failed")} onClick={() => onRetryAllFailedJobs?.()}>
          Retry all failed
        </button>
      </div>
      <div style={{
        fontSize: 11, color: "var(--ink-faint)",
        textTransform: "uppercase", letterSpacing: ".08em",
        margin: "0 0 8px"
      }}>Live</div>
      {live.length === 0 && (
        <p style={{color: "var(--ink-faint)", fontSize: 13, margin: "0 0 16px"}}>No jobs running.</p>
      )}
      {live.map(j => <JobCard key={j.id} job={j} canEdit={canEdit} onRetryJob={onRetryJob} onCancelJob={onCancelJob} onViewDetail={openDetail} detailBusy={detailBusy} />)}

      <div style={{
        fontSize: 11, color: "var(--ink-faint)",
        textTransform: "uppercase", letterSpacing: ".08em",
        margin: "14px 0 8px"
      }}>Recent</div>
      {done.map(j => <JobCard key={j.id} job={j} canEdit={canEdit} onRetryJob={onRetryJob} onCancelJob={onCancelJob} onViewDetail={openDetail} detailBusy={detailBusy} />)}

      {detail && (
        <div className="op-block" style={{marginTop: 12}}>
          <div className="op-block-head">
            <h3>Job detail #{detail.id}</h3>
            <button className="btn ghost sm" onClick={() => setDetail(null)}><Icon d={IC.close} /></button>
          </div>
          <div className="op-block-body" style={{display: "grid", gap: 8}}>
            <div className="job-meta"><span>{detail.type}</span><span>{detail.status}</span></div>
            <div className="job-meta"><span>by {detail.requested_by}</span><span>{fmtFull(detail.created_at_utc)}</span></div>
            {detail.error_text && <div style={{color: "var(--err)", fontSize: 12}}>{detail.error_text}</div>}
            <div style={{fontSize: 12, color: "var(--ink-faint)"}}>Events</div>
            <div style={{display: "grid", gap: 6, maxHeight: 220, overflow: "auto"}}>
              {(detail.events || []).map((ev, idx) => (
                <div key={`${ev.created_at_utc || ""}-${idx}`} className="audit-row">
                  <span className="when">{fmtFull(ev.created_at_utc)}</span>
                  <span className="by">[{ev.level}] {ev.message}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function JobCard({ job, canEdit, onRetryJob, onCancelJob, onViewDetail, detailBusy }) {
  const badgeStatus =
    job.state === "complete" ? "fresh" :
    job.state === "failed" ? "failed" :
    job.state === "running" ? "running" :
    job.state === "cancelled" ? "stale" :
    "queued";
  return (
    <div className="job">
      <div className="job-head">
        <span className="job-id">{job.id}</span>
        <span className="job-action">{job.action}</span>
        <StatusBadge status={badgeStatus} />
      </div>
      <div className="job-target">{job.target}</div>
      {(job.state === "running" || job.state === "queued") && (
        <div className={`bar indeterminate`}><div className="bar-fill" /></div>
      )}
      <div className="job-meta">
        <span>by {job.by}</span>
        <span>{job.state === "complete" ? fmtDur(job.duration_ms) : fmtAgo(job.started)}</span>
      </div>
      {job.error && <div style={{marginTop: 6, color: "var(--err)", fontSize: 12}}>{job.error}</div>}
      <div style={{display: "flex", gap: 6, marginTop: 8}}>
        <button className="btn sm" disabled={!canEdit || job.state !== "failed"} onClick={() => onRetryJob?.(job.job_id)}>Retry</button>
        <button className="btn sm" disabled={!canEdit || job.state !== "queued"} onClick={() => onCancelJob?.(job.job_id)}>Cancel</button>
        <button className="btn sm" disabled={!job.job_id || detailBusy} onClick={() => onViewDetail?.(job.job_id)}>{detailBusy ? "Loading..." : "Details"}</button>
      </div>
    </div>
  );
}

function HistoryTab({ jobs, historyRows, onExportHistoryCsv }) {
  if (historyRows && historyRows.length > 0) {
    return (
      <div>
        <div style={{display: "flex", justifyContent: "flex-end", marginBottom: 8}}>
          <button className="btn sm" onClick={() => onExportHistoryCsv?.()}>Export CSV</button>
        </div>
        {historyRows.map((h) => (
          <div key={h.id} className="audit-row">
            <span className="when">{fmtFull(h.created_at_utc)}</span>
            <span className="by"><strong style={{color:"var(--ink)"}}>{h.actor}</strong> ran <code style={{font:"var(--t-mono-sm)"}}>{h.action}</code> → {h.target_ref || "—"}</span>
            <span className="result" style={{color: h.result === "ok" ? "var(--ok)" : "var(--err)"}}>{h.result}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div>
      {jobs.map(j => (
        <div key={j.id} className="audit-row">
          <span className="when">{fmtFull(j.started)}</span>
          <span className="by"><strong style={{color:"var(--ink)"}}>{j.by}</strong> ran <code style={{font:"var(--t-mono-sm)"}}>{j.action}</code> → {j.target}</span>
          <span className="result" style={{color: j.state === "failed" ? "var(--err)" : "var(--ink-soft)"}}>
            {j.state === "complete" ? fmtDur(j.duration_ms) : j.state}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------- toasts ----------
function Toasts({ toasts, dismiss }) {
  return (
    <div className="toasts">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.kind || ""}`}>
          <span className="ico" />
          <span style={{flex:1}}>{t.text}</span>
          <button onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
        </div>
      ))}
    </div>
  );
}

// ---------- command palette ----------
function Palette({ open, onClose, pages, onPick, onAction }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQ(""); setSel(0);
      setTimeout(() => inputRef.current?.focus(), 20);
    }
  }, [open]);

  const items = useMemo(() => {
    const actions = [
      { type: "action", id: "act-refresh-all", label: "Refresh all pages", tag: "operation", run: () => onAction("refresh_all", "") },
      { type: "action", id: "act-add",         label: "Add URL + mirror…",  tag: "operation", run: () => onAction("focus_add", "") },
    ];
    const pageItems = pages.map(p => ({
      type: "page", id: p.slug, label: p.title, tag: p.collection, page: p,
    }));
    const all = [...actions, ...pageItems];
    if (!q.trim()) return all.slice(0, 12);
    const qq = q.toLowerCase();
    return all.filter(it => it.label.toLowerCase().includes(qq) || (it.tag || "").toLowerCase().includes(qq)).slice(0, 20);
  }, [q, pages, onAction]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, items.length - 1)); }
      else if (e.key === "ArrowUp")   { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const it = items[sel];
        if (!it) return;
        if (it.type === "page") onPick(it.page);
        else it.run?.();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, items, sel, onPick, onClose]);

  return (
    <div className={`palette-scrim${open ? " open" : ""}`} onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          placeholder="Search pages, actions, collections…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setSel(0); }}
        />
        <div className="palette-list">
          {items.length === 0 && (
            <div style={{padding:"20px 14px", color:"var(--ink-faint)", fontSize: 13}}>No matches.</div>
          )}
          {items.map((it, i) => (
            <div
              key={it.id}
              className={`palette-row${i === sel ? " active" : ""}`}
              onMouseEnter={() => setSel(i)}
              onClick={() => {
                if (it.type === "page") onPick(it.page);
                else it.run?.();
                onClose();
              }}
            >
              <Icon d={it.type === "page" ? IC.grid : IC.terminal} />
              <span>{it.label}</span>
              <span className="tag-k">{it.tag}</span>
            </div>
          ))}
        </div>
        <div className="palette-foot">
          <span>↑↓ navigate · ↵ select · esc close</span>
          <span>⌘K</span>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Drawer, Ops, Toasts, Palette });
