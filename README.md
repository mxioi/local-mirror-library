# Local Mirror Library

[![CI](https://github.com/mxioi/local-mirror-library/actions/workflows/ci.yml/badge.svg)](https://github.com/mxioi/local-mirror-library/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Mirror selected Wikipedia/RFC pages into a local archive with a modern UI, FastAPI backend, job queue, role-based auth, and admin tooling.

## Why this project

- Keep critical docs available offline.
- Mirror only the pages you care about (not a full crawl).
- Manage refresh jobs, history, and users from one interface.
- Deploy quickly on metal, Docker Compose, or Kubernetes.

## Features

- Search/filter library UI (cards + list, tags, facets, saved filters)
- FastAPI backend with SQLite metadata and async job worker
- Auth modes: local accounts and AD/LDAP sign-in
- Admin panel: users, password resets, API keys, system snapshot, logs
- Snapshot timeline + audit trail + CSV history export
- Installer for Windows/Linux/macOS deployment flows

## Quickstart (recommended)

### Windows

```powershell
./install.ps1
```

### Linux/macOS

```bash
chmod +x install.sh
./install.sh
```

Installer modes:

1. Python on metal
2. Docker Compose
3. Kubernetes

## Access URLs

- UI: `http://<host>:8080/Local%20Mirror%20Library.html`
- API health: `http://<host>:8010/api/v1/health`

## Deployment options

### 1) Python on metal

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp config/app.example.yaml config/app.yaml
cp .env.example .env
python archive_backend.py --check --settings config/app.yaml --env-file .env
python archive_backend.py --serve --settings config/app.yaml --env-file .env
python -m http.server 8080
```

### 2) Docker Compose

```bash
cp config/app.example.yaml config/app.yaml
cp .env.example .env
docker compose up -d --build
docker compose ps
```

### 3) Kubernetes

```bash
docker build -t local-mirror:latest .
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl -n local-mirror get pods,svc
```

## Configuration

- Main settings template: `config/app.example.yaml`
- Environment overrides template: `.env.example`
- Runtime precedence: CLI args > env vars > YAML file > defaults

Common fields to set for your environment:

- `ALLOWED_ORIGINS`
- `AD_SERVER`, `AD_DOMAIN`, `AD_USE_SSL`
- paths under `paths.*` in `config/app.yaml`

## Security + operations

- Review `SECURITY.md` before production exposure.
- Never commit real secrets in `.env`/K8s secrets.
- Keep regular backups of:
  - `wikipedia-local/library.db`
  - `wikipedia-local/manifest.json`
  - `wikipedia-pages.json`
  - `config/app.yaml`
- See `docs/OPERATIONS.md` and `docs/upgrade.md` for runbook/upgrade guidance.

## Project docs

- Setup details: `README-wikipedia-mirror.md`
- Frontend/backend endpoint mapping: `FRONTEND_API_INTEGRATION.md`
- Roadmap: `PROJECT_ROADMAP.md`
- Contributing: `CONTRIBUTING.md`
