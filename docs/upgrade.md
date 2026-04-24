# Upgrade Notes

## Configuration migration

This release introduces centralized runtime settings:

- `config/app.yaml`
- `.env`

If you were using only environment variables before, behavior remains backward compatible.

## Validation checklist

Run after upgrade:

```bash
python archive_backend.py --check --settings config/app.yaml --env-file .env
```

Expected result: `Preflight checks: OK`.
