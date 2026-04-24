# Security Policy

## Reporting vulnerabilities

Please report vulnerabilities privately to maintainers. Do not open public issues for exploitable security bugs.

Include:

- Affected version/commit
- Reproduction steps
- Impact assessment
- Suggested remediation (optional)

## Hardening guidance

- Use strong `ARCHIVE_ADMIN_PASSWORD` during bootstrap.
- Restrict `ALLOWED_ORIGINS` to trusted frontends only.
- Prefer LDAPS (`AD_USE_SSL=1`) for AD authentication.
- Keep `.env` out of source control.
- Run behind reverse proxy/TLS for external access.
