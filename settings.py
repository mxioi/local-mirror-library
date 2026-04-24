from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"").strip("'")
    return values


def _deep_get(data: dict[str, Any], dotted_key: str, default: Any) -> Any:
    node: Any = data
    for key in dotted_key.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _resolve_path(raw: str | Path, base_dir: Path) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Settings file must be a YAML object")
    return loaded


@dataclass
class ArchiveSettings:
    settings_path: Path
    env_file: Path
    db_path: Path
    config_path: Path
    manifest_path: Path
    output_root: Path
    log_path: Path
    server_host: str
    server_port: int
    library_port: int
    library_home_url: str
    frontend_api_base: str
    allowed_origins: list[str]
    ad_server: str
    ad_domain: str
    ad_use_ssl: bool
    bootstrap_admin_password: str
    session_hours: int
    max_jobs_age_days: int
    max_db_size_mb: int


def load_archive_settings(settings_path: Path | None = None, env_file: Path | None = None) -> ArchiveSettings:
    settings_path = (settings_path or Path("config/app.yaml")).resolve()
    env_file = (env_file or Path(".env")).resolve()
    base_dir = settings_path.parent.parent if settings_path.parent.name == "config" else settings_path.parent

    yaml_data = _load_yaml(settings_path)
    env_data = _read_env_file(env_file)

    def env(name: str, default: str = "") -> str:
        if name in os.environ:
            return str(os.environ[name])
        if name in env_data:
            return env_data[name]
        return default

    def pick(dotted: str, env_name: str, fallback: Any) -> Any:
        yaml_value = _deep_get(yaml_data, dotted, None)
        if env_name in os.environ or env_name in env_data:
            return env(env_name, "")
        if yaml_value is not None:
            return yaml_value
        return fallback

    allowed_origins_raw = pick("server.allowed_origins", "ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    if isinstance(allowed_origins_raw, str):
        allowed_origins = [x.strip() for x in allowed_origins_raw.split(",") if x.strip()]
    elif isinstance(allowed_origins_raw, list):
        allowed_origins = [str(x).strip() for x in allowed_origins_raw if str(x).strip()]
    else:
        allowed_origins = list(DEFAULT_ALLOWED_ORIGINS)

    return ArchiveSettings(
        settings_path=settings_path,
        env_file=env_file,
        db_path=_resolve_path(str(pick("paths.db", "ARCHIVE_DB_PATH", "wikipedia-local/library.db")), base_dir),
        config_path=_resolve_path(str(pick("paths.config", "ARCHIVE_CONFIG_PATH", "wikipedia-pages.json")), base_dir),
        manifest_path=_resolve_path(str(pick("paths.manifest", "ARCHIVE_MANIFEST_PATH", "wikipedia-local/manifest.json")), base_dir),
        output_root=_resolve_path(str(pick("paths.output_root", "ARCHIVE_OUTPUT_ROOT", "wikipedia-local")), base_dir),
        log_path=_resolve_path(str(pick("paths.log", "ARCHIVE_LOG_PATH", "wikipedia-local/archive.log")), base_dir),
        server_host=str(pick("server.host", "ARCHIVE_HOST", "0.0.0.0")),
        server_port=int(str(pick("server.port", "ARCHIVE_PORT", 8010))),
        library_port=int(str(pick("server.library_port", "ARCHIVE_LIBRARY_PORT", 8080))),
        library_home_url=str(pick("server.library_home_url", "ARCHIVE_LIBRARY_HOME_URL", "http://localhost:8080/Local%20Mirror%20Library.html")),
        frontend_api_base=str(pick("server.frontend_api_base", "ARCHIVE_FRONTEND_API_BASE", "")),
        allowed_origins=allowed_origins,
        ad_server=str(pick("auth.ad_server", "AD_SERVER", "ad.example.local")),
        ad_domain=str(pick("auth.ad_domain", "AD_DOMAIN", "example.local")),
        ad_use_ssl=_parse_bool(str(pick("auth.ad_use_ssl", "AD_USE_SSL", "0"))),
        bootstrap_admin_password=str(pick("auth.bootstrap_admin_password", "ARCHIVE_ADMIN_PASSWORD", "")),
        session_hours=max(1, int(str(pick("auth.session_hours", "ARCHIVE_SESSION_HOURS", 12)))),
        max_jobs_age_days=max(1, int(str(pick("limits.max_jobs_age_days", "MAX_JOBS_AGE_DAYS", 30)))),
        max_db_size_mb=max(50, int(str(pick("limits.max_db_size_mb", "MAX_DB_SIZE_MB", 500)))),
    )
