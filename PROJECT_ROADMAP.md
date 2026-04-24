# Production & Open-Source Readiness Roadmap

Status snapshot: completed in this delivery.

## Phase 0 - Definition & release criteria

- Defined setup modes: metal, Docker Compose, Kubernetes.
- Defined baseline release artifacts: installer, config templates, runtime checks, docs, CI.

## Phase 1 - Configuration foundation

- Added shared settings loader: `settings.py`.
- Added config templates: `config/app.example.yaml`, `.env.example`.
- Refactored backend and mirror scripts to consume centralized settings.

## Phase 2 - Packaging

- Added pinned Python dependencies in `requirements.txt`.
- Added `Dockerfile`, `.dockerignore`, and `docker-compose.yml`.
- Added Kubernetes manifests under `k8s/`.

## Phase 3 - Onboarding installer

- Added entrypoint scripts: `install.ps1`, `install.sh`.
- Added interactive installer: `installer/main.py`.
- Installer supports:
  - Python on metal
  - Docker Compose
  - Kubernetes

## Phase 4 - Operational baseline

- Added installer-driven environment/config generation.
- Added preflight checks into installer metal flow.
- Added persistent volume paths for compose/k8s patterns.

## Phase 5 - Security baseline

- Added `SECURITY.md`.
- Added defaults/docs for CORS and AD auth environment values.
- Added `.gitignore` protections for local secrets/config.

## Phase 6 - Open-source docs

- Added top-level `README.md` quickstart.
- Added `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE`.

## Phase 7 - CI quality gates

- Added GitHub Actions workflow: `.github/workflows/ci.yml`.
- Includes dependency install, compile checks, backend preflight, and Docker build smoke.

## Phase 8 - GA handoff checklist

- Artifacts in place for first public release candidate.
- Remaining recommended work before broad public rollout:
  - Expand automated tests for auth/jobs/admin APIs.
  - Add Helm chart option (currently raw manifests).
  - Add upgrade/migration notes per release.
