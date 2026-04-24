# Wikipedia Local Mirror

This folder contains a small utility to mirror selected Wikipedia pages for local serving while avoiding a crawl of linked article pages.

## Fast onboarding

Use the installer to pick deployment mode:

- `./install.ps1` (Windows)
- `./install.sh` (Linux/macOS)

Modes:

1. Python on metal
2. Docker Compose
3. Kubernetes

## Files

- `mirror_wikipedia_pages.py` - main mirroring script
- `archive_backend.py` - Phase 1 backend foundation (SQLite + sync + API)
- `FRONTEND_API_INTEGRATION.md` - endpoint mapping for UI components/tabs
- `login-page.jsx` - dedicated login screen component
- `admin-panel.jsx` - admin-only account management view
- `wikipedia-pages.json` - list of pages to mirror
- `wikipedia-local/` - generated output (safe to regenerate)

## Library UI

The generated `wikipedia-local/index.html` includes a richer local library interface:

- Search across title, oldid, source URL, and source host
- Collection filter (for organizing larger archives)
- Collection sidebar facets with counts and collection landing pages
- Archive timestamp display (`archived_at_utc` per page)
- Card-style browsing with quick links to local copy and source page
- Optional action panel (run add/update/mirror tasks from UI)

## Mirrored page overlay

Each mirrored article includes a bottom-right overlay with:

- `Library home` link (default points to `http://localhost:8080/Local%20Mirror%20Library.html`)
- `Page timeline` entries for available local snapshots of that same page title

To create timeline entries for one page, add multiple config entries with the same `title` and different `oldid` values.

Example:

```json
{
  "pages": [
    { "title": "IPv4", "oldid": "1348847330" },
    { "title": "IPv4", "oldid": "1200000000" }
  ]
}
```

To override library home link during build:

```bash
python mirror_wikipedia_pages.py --library-home-url "http://127.0.0.1:8080/Local%20Mirror%20Library.html"
```

### UI actions mode

To use run-buttons directly inside the GUI, run the integrated server:

```bash
python mirror_wikipedia_pages.py --serve
```

This serves `wikipedia-local/` and enables `/api/run` actions used by the UI buttons.

## Add more pages

Edit `wikipedia-pages.json` and append more entries under `pages`:

```json
{
  "pages": [
    { "title": "IPv4", "oldid": "1348847330" },
    { "title": "IPv6", "oldid": "1348704875" },
    { "title": "Internet_Protocol" }
  ]
}
```

- `title` is required.
- `oldid` is optional; include it when you want a revision-pinned snapshot.
- `collection` is optional and defaults to `Wikipedia`.

Or add pages directly from URLs (auto-resolves latest `oldid` if URL does not include one):

```bash
python mirror_wikipedia_pages.py --add-url "https://en.wikipedia.org/wiki/Border_Gateway_Protocol"
```

Add multiple URLs in one run:

```bash
python mirror_wikipedia_pages.py --add-url "https://en.wikipedia.org/wiki/IPv6" --add-url "https://en.wikipedia.org/wiki/Classless_Inter-Domain_Routing"
```

Add one URL and mirror only that page:

```bash
python mirror_wikipedia_pages.py --add-url "https://en.wikipedia.org/wiki/OSPF" --mirror-added-only
```

Update one specific page (latest oldid) and mirror only that page:

```bash
python mirror_wikipedia_pages.py --refresh-oldids --only-url "https://en.wikipedia.org/wiki/Domain_Name_System"
```

Update all pages (latest oldids) and mirror all pages:

```bash
python mirror_wikipedia_pages.py --refresh-oldids
```

## Build mirrors

```bash
python mirror_wikipedia_pages.py --clean
```

Useful options:

- Mirror only one specific configured page:

  ```bash
  python mirror_wikipedia_pages.py --only-title "Domain_Name_System"
  ```

- Mirror only one specific configured page by URL:

  ```bash
  python mirror_wikipedia_pages.py --only-url "https://en.wikipedia.org/wiki/IPv4"
  ```

- Refresh only a specific page oldid, then mirror only that page:

  ```bash
  python mirror_wikipedia_pages.py --refresh-oldids --only-title "IPv4"
  ```

- Refresh all existing entries to latest oldid, then mirror all pages:

  ```bash
  python mirror_wikipedia_pages.py --refresh-oldids
  ```

- Update config only (no mirror run):

  ```bash
  python mirror_wikipedia_pages.py --add-url "https://en.wikipedia.org/wiki/OSPF" --no-mirror
  ```

## Serve locally

```bash
python -m http.server 8080
```

Or with action API enabled:

```bash
python mirror_wikipedia_pages.py --serve
```

Open:

- `http://localhost:8080/wikipedia-local/index.html`

## Notes

- The script pulls HTML/CSS/page-required assets only for each configured page.
- If a Wikipedia link points to another page that is also in `wikipedia-pages.json`, it is rewritten to the local mirrored copy.
- A small "Local mirrors" menu is injected on each mirrored page with links to the local library home and all mirrored pages.
- Links to pages not in your config stay as online Wikipedia links.
- Output includes `wikipedia-local/manifest.json` for tracking mirrored pages.

## Backend (SQLite + API + jobs)

The backend is implemented in `archive_backend.py` and provides:

- SQLite metadata store (`wikipedia-local/library.db`)
- Sync from `wikipedia-pages.json` + `wikipedia-local/manifest.json`
- Query APIs (items/facets/history)
- Async operations queue and worker (jobs)
- Role-based permissions (`viewer`, `operator`, `admin`) via request headers

Initialize and sync database:

```bash
python archive_backend.py --init-db --sync --stats
```

Start API server (requires FastAPI + Uvicorn):

```bash
pip install fastapi uvicorn slowapi bcrypt
python archive_backend.py --serve --host 0.0.0.0 --port 8010
```

Preflight checks:

```bash
python archive_backend.py --check
python archive_backend.py --check --check-wikipedia
```

Phase 1 auth hardening is enabled:

- Bearer token auth (`Authorization: Bearer <token>`) is required for protected endpoints.
- Login endpoint: `POST /api/v1/auth/login`
- API key login endpoint: `POST /api/v1/auth/api-key-login`
- Logout endpoint: `POST /api/v1/auth/logout`
- Current session endpoint: `GET /api/v1/auth/me`
- Change password endpoint: `POST /api/v1/auth/change-password` (local users)

Bootstrap local admin password (first setup):

```bash
$env:ARCHIVE_ADMIN_PASSWORD="REPLACE_ME"
python archive_backend.py --init-db --sync --stats
```

AD on-prem authentication (LDAP bind) is supported for login:

- Default domain assumption: `example.local`
- Default server: `ad.example.local`

Optional env vars:

- `AD_SERVER` (default: `ad.example.local`)
- `AD_DOMAIN` (default: `example.local`)
- `AD_USE_SSL` (`1` for LDAPS, default `0`)

CORS is now restricted via `ALLOWED_ORIGINS`:

```bash
$env:ALLOWED_ORIGINS="http://localhost:8080,http://127.0.0.1:8080,http://<your-host-or-ip>:8080"
python archive_backend.py --serve
```

If login shows `Failed to fetch`, check:

- frontend API base points to your server host (not browser localhost)
- backend is reachable on `http://<server-ip>:8010`
- backend started with `--host 0.0.0.0` for LAN clients
- `ALLOWED_ORIGINS` contains the exact frontend origin (scheme + host + port)

Role headers for API testing:

- (replaced by bearer token auth)

Read endpoints:

- `GET /api/v1/health`
- `GET /api/v1/me`
- `GET /api/v1/me/settings`
- `GET /api/v1/items`
- `GET /api/v1/items/{id}`
- `GET /api/v1/jobs-sse` (SSE stream)
- `GET /api/v1/facets`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/history`
- `GET /api/v1/history.csv` (CSV export)
- `GET /api/v1/saved-filters`
- `GET /api/v1/admin/system` (admin)

Write endpoints:

- `POST /api/v1/admin/sync` (admin)
- `POST /api/v1/actions/add-url` (operator)
- `POST /api/v1/actions/mirror-one` (operator)
- `POST /api/v1/actions/mirror-by-url` (operator)
- `POST /api/v1/actions/refresh-one` (operator)
- `POST /api/v1/actions/refresh-all` (operator)
- `POST /api/v1/jobs/{id}/retry` (operator)
- `POST /api/v1/jobs/retry-failed` (operator)
- `POST /api/v1/jobs/{id}/cancel` (operator, queued only)
- `POST /api/v1/saved-filters`
- `POST /api/v1/me/settings`
- `POST /api/v1/items/{id}/tags`
- `DELETE /api/v1/items/{id}/tags/{tag}`
- `DELETE /api/v1/items/{id}` (soft delete)
- `DELETE /api/v1/saved-filters/{name}`
- `POST /api/v1/admin/users/{username}/reset-password` (admin, local users)
- `POST /api/v1/admin/users/{username}/api-key` (admin, returns one-time API key)

Admin user creation/update notes:

- `POST /api/v1/admin/users` accepts optional `password` and `auth_source` fields.
- Provide `password` + `auth_source: "local"` to create/manage local service accounts.
- `POST /api/v1/admin/cleanup` (admin)
- `GET /api/v1/admin/logs` (admin)

Source support notes:

- `add-url` accepts Wikipedia, RFC Editor, and generic HTML URLs.
- Non-Wikipedia URLs are mirrored directly from their source URL (no oldid refresh).
- Generic HTML/RFC pages are sanitized to remove navigation-heavy chrome (`nav/header/footer/aside`, scripts) before local archiving.
