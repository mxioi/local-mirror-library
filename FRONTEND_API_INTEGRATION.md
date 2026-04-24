# Frontend-Backend Integration Guide

This document maps the current UI features (Library, Operations, Jobs, History, Saved Filters, Role simulation) to the implemented backend API in `archive_backend.py`.

Base URL (default):

- `http(s)://<current-frontend-host>:8010`

Current prototype wiring status:

- `app.jsx` now calls backend endpoints directly (with mock fallback when API is offline).
- `panels.jsx` history and drawer actions consume backend-driven jobs/audit where available.
- `login-page.jsx` provides the dedicated sign-in component used before app shell load.
- `admin-panel.jsx` provides the primary admin user-management view (admin role only).
- `runtime-config.js` can explicitly set `window.ARCHIVE_API_BASE` at load time (installer writes this file).
- `data.js` still infers `ARCHIVE_API_BASE` from current page host (`http(s)://<current-host>:8010/api/v1`) when no explicit runtime override is present.

Required headers for role simulation:

- `Authorization: Bearer <token>`

Login flow:

- `POST /api/v1/auth/login` with `{ username, password }`
- optional service-to-service login: `POST /api/v1/auth/api-key-login` with `{ username, api_key }`
- Store `access_token` in localStorage
- Call `GET /api/v1/auth/me` after login to load role/capabilities
- `auth/me` profile includes `auth_source` (`local` or `ad`) for account-security UI gating

Example common fetch helper:

```js
const API = `${window.location.protocol === "https:" ? "https" : "http"}://${window.location.hostname}:8010/api/v1`

async function api(path, options = {}, role = "viewer", user = "frontend-user") {
async function api(path, options = {}, token = "") {
  const headers = {
    ...(options.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  if (!headers["Content-Type"] && options.body) headers["Content-Type"] = "application/json"
  const res = await fetch(`${API}${path}`, { ...options, headers })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`)
  return body
}
```

## 1) Library Grid/List

Use `GET /items` with query params.

Query params:

- `q`
- `collection`
- `status`
- `source`
- `tag`
- `sort=archived_at|title|size`
- `order=asc|desc`
- `limit`
- `offset`

Example:

```js
const data = await api(
  `/items?q=${encodeURIComponent(search)}&collection=${encodeURIComponent(collection)}&status=${encodeURIComponent(status)}&source=${encodeURIComponent(source)}&tag=${encodeURIComponent(tag)}&sort=${sort}&order=${order}&limit=${limit}&offset=${offset}`,
  { method: "GET" },
  token
)

// data: { items: [...], total, limit, offset }
```

## 2) Facets (Collections / Status / Source / Tags)

Use `GET /facets`.

```js
const facets = await api(`/facets`, { method: "GET" }, "viewer")
// facets: { collections: [{name,count}], statuses:[...], sources:[...], tags:[...] }
```

## 3) Detail Drawer

Use `GET /items/{id}`.

```js
const detail = await api(`/items/${id}`, { method: "GET" }, "viewer")
// detail.item includes metadata + tags + item-level audit entries
```

Tag management:

- `POST /api/v1/items/{id}/tags` body: `{ "tag": "networking" }`
- `DELETE /api/v1/items/{id}/tags/{tag}`

Item deletion:

- `DELETE /api/v1/items/{id}` body: `{ "reason": "No longer needed" }`

## 4) Operations Console (Run tab)

All operation endpoints are async: they return a `job_id`.

### Add URL + mirror only added

- `POST /actions/add-url`
- body: `{ "url": "https://en.wikipedia.org/wiki/Domain_Name_System" }`

### Mirror by title

- `POST /actions/mirror-one`
- body: `{ "title": "IPv4" }`

### Mirror by URL

- `POST /actions/mirror-by-url`
- body: `{ "url": "https://en.wikipedia.org/wiki/IPv4" }`

### Refresh one

- `POST /actions/refresh-one`
- body: `{ "title": "IPv4" }`

### Refresh all

- `POST /actions/refresh-all`
- body: `{}` (or no body)

Example operation call:

```js
const run = await api(
  "/actions/refresh-one",
  { method: "POST", body: JSON.stringify({ title: "IPv4" }) },
  token
)
// run: { ok: true, job_id }
```

## 5) Jobs Tab

### List jobs

- `GET /jobs?limit=40&offset=0`
- includes parsed `payload` for better target rendering

### Job detail

- `GET /jobs/{id}`
- includes events timeline + payload + result + error

### Retry failed job

- `POST /jobs/{id}/retry` (operator+)
- `POST /jobs/retry-failed` (operator+)

### Cancel queued job

- `POST /jobs/{id}/cancel` (operator+, queued only)

### Live stream

- `GET /api/v1/jobs-sse?token=<bearer-token>` (SSE)

Polling pattern:

```js
async function waitForJob(jobId) {
  while (true) {
    const { job } = await api(`/jobs/${jobId}`, { method: "GET" }, "viewer")
    if (job.status === "completed" || job.status === "failed") return job
    await new Promise((r) => setTimeout(r, 1000))
  }
}
```

## 6) History Tab

Use `GET /history?limit=100&offset=0`.

```js
const history = await api(`/history?limit=100&offset=0`, { method: "GET" }, "viewer")
```

CSV export endpoint:

- `GET /api/v1/history.csv?limit=2000` (requires bearer token)

## 7) Saved Filters

### List

- `GET /saved-filters`

### Upsert

- `POST /saved-filters`
- body: `{ "name": "Routing only", "query": { "collection": "Wikipedia", "tag": "routing" } }`

### Delete

- `DELETE /saved-filters/{name}`

## 8) Role Simulation in UI

Use `GET /me` to retrieve capabilities:

```js
const me = await api(`/me`, { method: "GET" }, currentRole, currentUser)
const me = await api(`/auth/me`, { method: "GET" }, token)
// me.capabilities: { can_read, can_operate, can_admin }
```

Recommended behavior:

- `viewer`: hide/disable operation buttons
- `operator`: allow Run + retry
- `admin`: allow sync and admin controls

## 9) Admin Sync

Use `POST /admin/sync` with bearer auth (admin role).

```js
await api(`/admin/sync`, { method: "POST" }, token)
```

Admin system snapshot endpoint:

- `GET /api/v1/admin/system`
- returns worker state, item/job counters, active sessions, and last job summary

## 9b) Admin user/role management

- `GET /api/v1/admin/users`
- `POST /api/v1/admin/users` body: `{ "username": "ops1", "role": "operator", "disabled": false, "password": "TempPass!123", "auth_source": "local" }`
- `DELETE /api/v1/admin/users/{username}`
- `POST /api/v1/admin/users/{username}/reset-password` body: `{ "new_password": "<new-password>" }`
- `POST /api/v1/admin/users/{username}/api-key` (returns one-time plaintext API key)
- `admin/users` rows include `auth_source`; disable reset-password actions for non-`local` users

Frontend structure:

- `login-page.jsx` is the dedicated sign-in screen.
- `admin-panel.jsx` is the primary admin-only tab/view for account management.

## 9c) Account password management

- `POST /api/v1/auth/change-password` body: `{ "old_password": "<current>", "new_password": "<new>" }`
- `POST /api/v1/admin/users/{username}/reset-password` is admin-only and local-auth only

Use these to back a permissions management panel in the frontend.

## 9d) User settings

- `GET /api/v1/me/settings`
- `POST /api/v1/me/settings` body: `{ "settings": { ... } }`

## 9e) Admin maintenance

- `POST /api/v1/admin/cleanup` body: `{ "purge_old_jobs": true, "days": 30 }`
- `GET /api/v1/admin/logs?lines=200`

## 10) Error Handling Contract

- Success: JSON body with endpoint-specific data
- Failure: HTTP 4xx/5xx with `detail` (FastAPI default)

UI recommendation:

- show toast on errors using `error.message`
- for operation endpoints, always route to Jobs tab after enqueue
- if a request returns `401`, clear stored token/user state and redirect to login
