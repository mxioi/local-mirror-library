# Contributing

Thanks for contributing.

## Development setup

1. Create virtual env and install deps:
   - `python -m venv .venv`
   - `pip install -r requirements.txt`
2. Copy config templates:
   - `cp config/app.example.yaml config/app.yaml`
   - `cp .env.example .env`
3. Run checks:
   - `python archive_backend.py --check --settings config/app.yaml --env-file .env`

## Pull requests

- Keep PRs focused and include a short test plan.
- Update docs when behavior or setup changes.
- Do not commit secrets (`.env`, private certs, credentials).

## Code style

- Python: clear, explicit, no hidden side effects.
- Frontend: maintain existing UI patterns and accessibility attributes.
