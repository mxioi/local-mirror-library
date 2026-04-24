# Operations Guide

## Backups

Backup these paths together:

- `wikipedia-local/library.db`
- `wikipedia-local/manifest.json`
- `wikipedia-pages.json`
- `config/app.yaml`

Example backup command:

```bash
tar -czf backup-$(date +%F).tgz wikipedia-local/library.db wikipedia-local/manifest.json wikipedia-pages.json config/app.yaml
```

## Restore

1. Stop running services.
2. Restore files to original locations.
3. Run: `python archive_backend.py --check --settings config/app.yaml --env-file .env`
4. Start services.

## Upgrades

1. Pull latest code.
2. Review `config/app.example.yaml` for new settings.
3. Reinstall dependencies (`pip install -r requirements.txt` or `docker compose build`).
4. Run preflight check before restart.
