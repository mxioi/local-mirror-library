import argparse
import hashlib
import logging
import secrets
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from settings import ArchiveSettings, load_archive_settings


DEFAULT_DB_PATH = Path("wikipedia-local/library.db")
DEFAULT_CONFIG_PATH = Path("wikipedia-pages.json")
DEFAULT_MANIFEST_PATH = Path("wikipedia-local/manifest.json")
DEFAULT_OUTPUT_ROOT = Path("wikipedia-local")
DEFAULT_ALLOWED_ORIGINS = "http://localhost:8080,http://127.0.0.1:8080"
DEFAULT_SESSION_HOURS = 12
DEFAULT_LOG_PATH = Path("wikipedia-local/archive.log")

ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}
logger = logging.getLogger("archive_backend")
RUNTIME_SETTINGS: ArchiveSettings = load_archive_settings()


def configure_runtime(settings_obj: ArchiveSettings) -> None:
    global RUNTIME_SETTINGS
    RUNTIME_SETTINGS = settings_obj


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_title_key(title: str) -> str:
    return title.strip().replace(" ", "_").casefold()


def snapshot_key(title: str, oldid: str | None) -> str:
    return f"{normalize_title_key(title)}@{(oldid or 'latest').strip() or 'latest'}"


def slugify(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in out:
        out = out.replace("--", "-")
    out = out.strip("-")
    return out or "default"


def source_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).netloc or "").lower() or None
    except Exception:
        return None


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "ak_" + secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    try:
        import bcrypt

        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except Exception:
        iterations = 390000
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
        return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    if str(password_hash).startswith("$2"):
        try:
            import bcrypt

            return bool(bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")))
        except Exception:
            return False
    try:
        algo, iter_s, salt, expected = password_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
        return secrets.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def configure_logging(log_path: Path = DEFAULT_LOG_PATH) -> None:
    if logger.handlers:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    rotating = RotatingFileHandler(str(log_path), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    rotating.setFormatter(formatter)
    logger.addHandler(rotating)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL UNIQUE,
            oldid TEXT,
            source_type TEXT NOT NULL DEFAULT 'wikipedia',
            source_url TEXT,
            source_host TEXT,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'pending',
            archived_at_utc TEXT,
            output_path TEXT,
            file_size_bytes INTEGER,
            deleted_at_utc TEXT,
            deleted_reason TEXT,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS item_tags (
            item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY(item_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            requested_role TEXT NOT NULL,
            idempotency_key TEXT,
            progress INTEGER NOT NULL DEFAULT 0,
            result_json TEXT,
            error_text TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at_utc TEXT,
            created_at_utc TEXT NOT NULL,
            started_at_utc TEXT,
            finished_at_utc TEXT
        );

        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_ref TEXT,
            result TEXT NOT NULL,
            metadata_json TEXT,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS saved_filters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            name TEXT NOT NULL,
            query_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            UNIQUE(owner, name)
        );

        CREATE TABLE IF NOT EXISTS user_profiles (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            display_name TEXT,
            password_hash TEXT,
            api_key_hash TEXT,
            auth_source TEXT NOT NULL DEFAULT 'local',
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            locked_until_utc TEXT,
            last_login_utc TEXT,
            disabled INTEGER NOT NULL DEFAULT 0,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL REFERENCES user_profiles(username) ON DELETE CASCADE,
            issued_at_utc TEXT NOT NULL,
            expires_at_utc TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0,
            client_ip TEXT,
            user_agent TEXT
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            username TEXT PRIMARY KEY REFERENCES user_profiles(username) ON DELETE CASCADE,
            settings_json TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection_id);
        CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
        CREATE INDEX IF NOT EXISTS idx_items_archived ON items(archived_at_utc);
        CREATE INDEX IF NOT EXISTS idx_items_title ON items(title);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at_utc);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at_utc);
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(username);
        CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON auth_sessions(expires_at_utc);

        CREATE VIRTUAL TABLE IF NOT EXISTS item_search USING fts5(
            normalized_title,
            title,
            oldid,
            source_url,
            content=''
        );
        """
    )
    _ensure_column(conn, "items", "source_type", "TEXT NOT NULL DEFAULT 'wikipedia'")
    _ensure_column(conn, "items", "source_url", "TEXT")
    _ensure_column(conn, "items", "source_host", "TEXT")
    _ensure_column(conn, "items", "status", "TEXT NOT NULL DEFAULT 'pending'")
    _ensure_column(conn, "items", "archived_at_utc", "TEXT")
    _ensure_column(conn, "items", "output_path", "TEXT")
    _ensure_column(conn, "items", "file_size_bytes", "INTEGER")
    _ensure_column(conn, "items", "deleted_at_utc", "TEXT")
    _ensure_column(conn, "items", "deleted_reason", "TEXT")
    _ensure_column(conn, "items", "updated_at_utc", "TEXT")
    _ensure_column(conn, "user_profiles", "password_hash", "TEXT")
    _ensure_column(conn, "user_profiles", "api_key_hash", "TEXT")
    _ensure_column(conn, "user_profiles", "auth_source", "TEXT NOT NULL DEFAULT 'local'")
    _ensure_column(conn, "user_profiles", "failed_login_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "user_profiles", "locked_until_utc", "TEXT")
    _ensure_column(conn, "user_profiles", "last_login_utc", "TEXT")
    _ensure_column(conn, "jobs", "retry_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "jobs", "next_attempt_at_utc", "TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_source_host ON items(source_host)")

    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)", (2, utc_now()))
    now = utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO user_profiles(username, role, display_name, auth_source, disabled, created_at_utc, updated_at_utc)
        VALUES ('frontend-user', 'admin', 'Frontend Admin', 'local', 0, ?, ?)
        """,
        (now, now),
    )

    bootstrap_password = str(RUNTIME_SETTINGS.bootstrap_admin_password or "").strip()
    if bootstrap_password:
        current = conn.execute("SELECT password_hash FROM user_profiles WHERE username = 'frontend-user'").fetchone()
        if current is not None and not str(current["password_hash"] or "").strip():
            conn.execute(
                "UPDATE user_profiles SET password_hash = ?, updated_at_utc = ? WHERE username = 'frontend-user'",
                (hash_password(bootstrap_password), now),
            )

    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column in cols:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def recover_running_jobs(conn: sqlite3.Connection) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE jobs
        SET status = 'failed', finished_at_utc = ?, error_text = COALESCE(error_text, 'Recovered after restart')
        WHERE status = 'running'
        """,
        (now,),
    )
    conn.commit()


def load_pages_from_config(config_path: Path) -> list[dict[str, Any]]:
    if not config_path.exists():
        return []
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    raw_pages = payload.get("pages", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_pages, list):
        raise ValueError("Config must be a list or object with 'pages' list.")

    pages: list[dict[str, Any]] = []
    for row in raw_pages:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip().replace(" ", "_")
        if not title:
            continue
        tags_raw = row.get("tags", [])
        tags: list[str] = []
        if isinstance(tags_raw, list):
            for t in tags_raw:
                txt = str(t).strip()
                if txt:
                    tags.append(txt)
        pages.append(
            {
                "title": title,
                "oldid": str(row.get("oldid", "")).strip(),
                "collection": str(row.get("collection", "Wikipedia")).strip() or "Wikipedia",
                "tags": tags,
                "source_type": str(row.get("source_type", "wikipedia")).strip().lower() or "wikipedia",
                "source_url": str(row.get("source_url", "")).strip(),
            }
        )
    return pages


def load_manifest_rows(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = payload.get("pages", []) if isinstance(payload, dict) else []
    if not isinstance(pages, list):
        return []

    out: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        title = str(page.get("title", "")).strip()
        if not title:
            continue
        oldid = str(page.get("oldid", "")).strip()
        row = dict(page)
        row["_title_key"] = normalize_title_key(title)
        row["_oldid"] = oldid
        out.append(row)
    return out


def find_manifest_row(manifest_rows: list[dict[str, Any]], title_key: str, oldid: str | None) -> dict[str, Any]:
    target_oldid = (oldid or "").strip()
    for row in manifest_rows:
        if row.get("_title_key") == title_key and str(row.get("_oldid", "")).strip() == target_oldid:
            return row
    for row in manifest_rows:
        if row.get("_title_key") == title_key:
            return row
    return {}


def ensure_collection(conn: sqlite3.Connection, name: str) -> int:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO collections(name, slug, created_at_utc, updated_at_utc)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET slug = excluded.slug, updated_at_utc = excluded.updated_at_utc
        """,
        (name, slugify(name), now, now),
    )
    row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise RuntimeError(f"Collection missing: {name}")
    return int(row["id"])


def ensure_tag(conn: sqlite3.Connection, name: str) -> int:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO tags(name, slug, created_at_utc, updated_at_utc)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET slug = excluded.slug, updated_at_utc = excluded.updated_at_utc
        """,
        (name, slugify(name), now, now),
    )
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise RuntimeError(f"Tag missing: {name}")
    return int(row["id"])


def file_size_from_output(output_path: str | None) -> int | None:
    if not output_path:
        return None
    path = Path(output_path)
    if not path.exists():
        return None
    try:
        return int(path.stat().st_size)
    except OSError:
        return None


def update_item_search_row(conn: sqlite3.Connection, normalized_title: str, title: str, oldid: str, source_url: str) -> None:
    conn.execute("DELETE FROM item_search WHERE normalized_title = ?", (normalized_title,))
    conn.execute(
        "INSERT INTO item_search(normalized_title, title, oldid, source_url) VALUES (?, ?, ?, ?)",
        (normalized_title, title, oldid, source_url),
    )


def sync_from_files(
    conn: sqlite3.Connection,
    config_path: Path,
    manifest_path: Path,
    actor: str = "system",
    role: str = "admin",
) -> dict[str, int]:
    pages = load_pages_from_config(config_path)
    manifest_rows = load_manifest_rows(manifest_path)
    seen: set[str] = set()
    inserted = 0
    updated = 0
    now = utc_now()

    for page in pages:
        title_key = normalize_title_key(page["title"])
        page_oldid = page["oldid"].strip() or None
        key = snapshot_key(page["title"], page_oldid)
        seen.add(key)
        m = find_manifest_row(manifest_rows, title_key, page_oldid)

        collection_id = ensure_collection(conn, page["collection"])
        oldid = page_oldid or str(m.get("oldid", "")).strip() or None
        source_type = str(page.get("source_type", "wikipedia") or "wikipedia").strip().lower() or "wikipedia"
        source_url = str(page.get("source_url", "")).strip() or str(m.get("source_url", "")).strip() or None
        archived_at = str(m.get("archived_at_utc", "")).strip() or None
        output_path = str(m.get("output", "")).strip() or None
        size_bytes = file_size_from_output(output_path)
        status = "archived" if archived_at else "pending"

        row = conn.execute("SELECT id FROM items WHERE normalized_title = ?", (key,)).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO items(
                    title, normalized_title, oldid, source_type, source_url, source_host,
                    collection_id, status, archived_at_utc, output_path, file_size_bytes,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page["title"],
                    key,
                    oldid or None,
                    source_type,
                    source_url,
                    source_host(source_url),
                    collection_id,
                    status,
                    archived_at,
                    output_path,
                    size_bytes,
                    now,
                    now,
                ),
            )
            inserted += 1
            item_id = int(conn.execute("SELECT id FROM items WHERE normalized_title = ?", (key,)).fetchone()["id"])
            audit(
                conn,
                actor=actor,
                role=role,
                action="item.insert",
                target_type="item",
                target_ref=str(item_id),
                result="ok",
                metadata={"title": page["title"], "oldid": oldid or ""},
            )
        else:
            conn.execute(
                """
                UPDATE items
                SET title = ?, oldid = ?, source_type = ?, source_url = ?, source_host = ?, collection_id = ?,
                    status = ?, archived_at_utc = ?, output_path = ?, file_size_bytes = ?, updated_at_utc = ?
                WHERE normalized_title = ?
                """,
                (
                    page["title"],
                    oldid or None,
                    source_type,
                    source_url,
                    source_host(source_url),
                    collection_id,
                    status,
                    archived_at,
                    output_path,
                    size_bytes,
                    now,
                    key,
                ),
            )
            updated += 1
            item_id = int(row["id"])
            audit(
                conn,
                actor=actor,
                role=role,
                action="item.update",
                target_type="item",
                target_ref=str(item_id),
                result="ok",
                metadata={"title": page["title"], "oldid": oldid or "", "status": status},
            )

        update_item_search_row(conn, key, page["title"], oldid, source_url or "")

        conn.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
        for tag_name in page["tags"]:
            tag_id = ensure_tag(conn, tag_name)
            conn.execute(
                "INSERT OR IGNORE INTO item_tags(item_id, tag_id, created_at_utc) VALUES (?, ?, ?)",
                (item_id, tag_id, now),
            )

    if seen:
        placeholders = ",".join("?" for _ in seen)
        conn.execute(
            f"UPDATE items SET status = 'missing', updated_at_utc = ? WHERE normalized_title NOT IN ({placeholders})",
            [now, *sorted(seen)],
        )

    conn.commit()
    return {"inserted": inserted, "updated": updated, "total": len(pages)}


def resolve_actor(conn: sqlite3.Connection, headers: dict[str, str]) -> tuple[str, str, dict[str, Any] | None]:
    user = (headers.get("x-user") or "frontend-user").strip() or "frontend-user"
    header_role_raw = (headers.get("x-role") or "").strip().lower()
    header_role = header_role_raw if header_role_raw in ROLE_LEVEL else ""

    row = conn.execute(
        "SELECT username, role, display_name, disabled FROM user_profiles WHERE username = ?",
        (user,),
    ).fetchone()

    if row is None:
        return user, (header_role or "viewer"), None

    if int(row["disabled"]):
        return user, "viewer", dict(row)

    role = header_role or str(row["role"] or "viewer").lower()
    if role not in ROLE_LEVEL:
        role = "viewer"
    return user, role, dict(row)


def require_role(role: str, minimum: str) -> None:
    if ROLE_LEVEL.get(role, 0) < ROLE_LEVEL.get(minimum, 0):
        raise PermissionError(f"Role '{role}' is not allowed for this operation (requires {minimum}+)")


def capability_for_role(role: str) -> dict[str, bool]:
    lvl = ROLE_LEVEL.get(role, 0)
    return {
        "can_read": lvl >= ROLE_LEVEL["viewer"],
        "can_operate": lvl >= ROLE_LEVEL["operator"],
        "can_admin": lvl >= ROLE_LEVEL["admin"],
    }


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 8, window_sec: int = 60) -> None:
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            items = [t for t in self._attempts.get(key, []) if now - t < self.window_sec]
            if len(items) >= self.max_attempts:
                self._attempts[key] = items
                return False
            items.append(now)
            self._attempts[key] = items
            return True


def create_session(conn: sqlite3.Connection, username: str, client_ip: str | None, user_agent: str | None) -> tuple[str, str]:
    token = secrets.token_urlsafe(40)
    token_hash = sha256_hex(token)
    issued = utc_now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=RUNTIME_SETTINGS.session_hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO auth_sessions(token_hash, username, issued_at_utc, expires_at_utc, revoked, client_ip, user_agent)
        VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (token_hash, username, issued, expires, client_ip, user_agent),
    )
    conn.commit()
    return token, expires


def revoke_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("UPDATE auth_sessions SET revoked = 1 WHERE token_hash = ?", (sha256_hex(token),))
    conn.commit()


def get_actor_from_token(conn: sqlite3.Connection, token: str) -> tuple[str, str, dict[str, Any] | None]:
    session = conn.execute(
        "SELECT username, expires_at_utc, revoked FROM auth_sessions WHERE token_hash = ?",
        (sha256_hex(token),),
    ).fetchone()
    if session is None:
        raise PermissionError("Invalid session token")
    if int(session["revoked"]):
        raise PermissionError("Session is revoked")
    expires_dt = parse_iso_utc(str(session["expires_at_utc"]))
    if expires_dt is None or expires_dt <= datetime.now(timezone.utc):
        raise PermissionError("Session expired")

    username = str(session["username"])
    profile = conn.execute(
        "SELECT username, role, display_name, disabled, auth_source FROM user_profiles WHERE username = ?",
        (username,),
    ).fetchone()
    if profile is None:
        raise PermissionError("User profile not found")
    if int(profile["disabled"]):
        raise PermissionError("User is disabled")
    role = str(profile["role"] or "viewer").lower()
    if role not in ROLE_LEVEL:
        role = "viewer"
    return username, role, dict(profile)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    value = authorization_header.strip()
    if not value.lower().startswith("bearer "):
        return None
    token = value[7:].strip()
    return token or None


def authenticate_ad(username: str, password: str, *, verbose: bool = False) -> tuple[bool, str]:
    """Returns (success, error_message). error_message is empty on success."""
    if not password:
        return False, "empty password"
    server_host = str(RUNTIME_SETTINGS.ad_server or "ad.example.local").strip()
    domain = str(RUNTIME_SETTINGS.ad_domain or "example.local").strip()
    use_ssl = bool(RUNTIME_SETTINGS.ad_use_ssl)

    try:
        from ldap3 import NTLM, Connection, Server
    except ImportError:
        return False, "ldap3 not installed — run: pip install ldap3"

    # OpenSSL 3.x disables MD4 but ldap3 NTLM needs it; patch via pycryptodome if available
    try:
        hashlib.new("md4", b"")
    except ValueError:
        try:
            from Crypto.Hash import MD4 as _CryptoMD4
            _real_hashlib_new = hashlib.new
            def _hashlib_new_with_md4(name, data=b"", **kw):
                if name == "md4":
                    h = _CryptoMD4.new()
                    if data:
                        h.update(data)
                    return h
                return _real_hashlib_new(name, data, **kw)
            hashlib.new = _hashlib_new_with_md4
        except ImportError:
            return False, "MD4 unavailable — run: pip install pycryptodome"

    ntlm_user = f"{domain}\\{username}" if "\\" not in username else username
    upn = username if "@" in username else f"{username}@{domain}"
    errors: list[str] = []

    # Attempt 1: NTLM with encryption (satisfies DC LDAP signing policy)
    try:
        from ldap3 import ENCRYPT
        server = Server(server_host, use_ssl=False, connect_timeout=5)
        conn = Connection(server, user=ntlm_user, password=password, authentication=NTLM,
                          session_security=ENCRYPT, auto_bind=True)
        conn.unbind()
        return True, ""
    except Exception as exc:
        errors.append(f"NTLM+ENCRYPT: {exc}")

    # Attempt 2: NTLM with signing only
    try:
        from ldap3 import SIGN
        server = Server(server_host, use_ssl=False, connect_timeout=5)
        conn = Connection(server, user=ntlm_user, password=password, authentication=NTLM,
                          session_security=SIGN, auto_bind=True)
        conn.unbind()
        return True, ""
    except Exception as exc:
        errors.append(f"NTLM+SIGN: {exc}")

    # Attempt 3: LDAPS on port 636 (requires cert on DC — works if ADCS is configured)
    try:
        from ldap3 import ANONYMOUS, Tls
        import ssl
        tls = Tls(validate=ssl.CERT_NONE)
        server = Server(server_host, port=636, use_ssl=True, tls=tls, connect_timeout=5)
        conn = Connection(server, user=ntlm_user, password=password, authentication=NTLM, auto_bind=True)
        conn.unbind()
        return True, ""
    except Exception as exc:
        errors.append(f"LDAPS+NTLM: {exc}")

    return False, " | ".join(errors)


def authenticate_local(conn: sqlite3.Connection, username: str, password: str) -> tuple[bool, dict[str, Any] | None]:
    row = conn.execute(
        "SELECT username, password_hash, failed_login_count, locked_until_utc, disabled FROM user_profiles WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return False, None
    if int(row["disabled"]):
        return False, dict(row)
    locked_until = parse_iso_utc(str(row["locked_until_utc"] or ""))
    if locked_until is not None and locked_until > datetime.now(timezone.utc):
        return False, dict(row)

    pw_hash = str(row["password_hash"] or "").strip()
    if not pw_hash:
        return False, dict(row)
    ok = verify_password(password, pw_hash)
    return ok, dict(row)


def update_local_password(conn: sqlite3.Connection, username: str, new_password: str) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE user_profiles
        SET password_hash = ?, auth_source = 'local', failed_login_count = 0, locked_until_utc = NULL, updated_at_utc = ?
        WHERE username = ?
        """,
        (hash_password(new_password), now, username),
    )


def audit(conn: sqlite3.Connection, actor: str, role: str, action: str, target_type: str, target_ref: str, result: str, metadata: dict[str, Any] | None = None) -> None:
    conn.execute(
        """
        INSERT INTO audit_events(actor, role, action, target_type, target_ref, result, metadata_json, created_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (actor, role, action, target_type, target_ref, result, json.dumps(metadata or {}), utc_now()),
    )


def enqueue_job(conn: sqlite3.Connection, job_type: str, payload: dict[str, Any], actor: str, role: str) -> int:
    now = utc_now()
    payload_json = json.dumps(payload)
    key = f"{job_type}:{payload_json}"
    existing = conn.execute(
        "SELECT id FROM jobs WHERE status IN ('queued','running') AND idempotency_key = ? ORDER BY id DESC LIMIT 1",
        (key,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])

    cur = conn.execute(
        """
        INSERT INTO jobs(type, status, payload_json, requested_by, requested_role, idempotency_key, created_at_utc)
        VALUES (?, 'queued', ?, ?, ?, ?, ?)
        """,
        (job_type, payload_json, actor, role, key, now),
    )
    job_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO job_events(job_id, level, message, created_at_utc) VALUES (?, 'info', ?, ?)",
        (job_id, "Job queued", now),
    )
    audit(conn, actor, role, "job.enqueue", "job", str(job_id), "ok", {"type": job_type, "payload": payload})
    conn.commit()
    return job_id


def claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    now = utc_now()
    row = conn.execute(
        "SELECT id FROM jobs WHERE status = 'queued' AND (next_attempt_at_utc IS NULL OR next_attempt_at_utc <= ?) ORDER BY id ASC LIMIT 1",
        (now,),
    ).fetchone()
    if row is None:
        return None
    job_id = int(row["id"])
    conn.execute("UPDATE jobs SET status = 'running', progress = 5, started_at_utc = ? WHERE id = ?", (now, job_id))
    conn.execute(
        "INSERT INTO job_events(job_id, level, message, created_at_utc) VALUES (?, 'info', ?, ?)",
        (job_id, "Job started", now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def complete_job(conn: sqlite3.Connection, job_id: int, ok: bool, result: dict[str, Any] | None, error_text: str | None) -> None:
    now = utc_now()
    status = "completed" if ok else "failed"
    conn.execute(
        "UPDATE jobs SET status = ?, progress = ?, result_json = ?, error_text = ?, finished_at_utc = ? WHERE id = ?",
        (status, 100 if ok else 100, json.dumps(result or {}), error_text, now, job_id),
    )
    conn.execute(
        "INSERT INTO job_events(job_id, level, message, created_at_utc) VALUES (?, ?, ?, ?)",
        (job_id, "info" if ok else "error", "Job completed" if ok else f"Job failed: {error_text}", now),
    )
    conn.commit()


def schedule_job_retry(conn: sqlite3.Connection, job_id: int, error_text: str, max_retries: int = 3) -> bool:
    row = conn.execute("SELECT retry_count FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return False
    retry_count = int(row["retry_count"] or 0)
    if retry_count >= max_retries:
        return False

    delay_sec = 15 * (2 ** retry_count)
    next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    now = utc_now()
    conn.execute(
        "UPDATE jobs SET status = 'queued', progress = 0, retry_count = retry_count + 1, next_attempt_at_utc = ?, error_text = ?, started_at_utc = NULL WHERE id = ?",
        (next_attempt, error_text, job_id),
    )
    conn.execute(
        "INSERT INTO job_events(job_id, level, message, created_at_utc) VALUES (?, 'warn', ?, ?)",
        (job_id, f"Auto-retry scheduled in {delay_sec}s (attempt {retry_count + 1}/{max_retries})", now),
    )
    conn.commit()
    return True


def perform_job_action(job_type: str, payload: dict[str, Any], config_path: Path, output_root: Path) -> str:
    import mirror_wikipedia_pages as mirror

    if job_type == "add_url":
        return mirror.execute_gui_action("add_url", str(payload.get("url", "")), config_path=config_path, output_root=output_root)
    if job_type == "mirror_title":
        return mirror.execute_gui_action("only_title", str(payload.get("title", "")), config_path=config_path, output_root=output_root)
    if job_type == "mirror_url":
        return mirror.execute_gui_action("only_url", str(payload.get("url", "")), config_path=config_path, output_root=output_root)
    if job_type == "refresh_one":
        return mirror.execute_gui_action("refresh_one", str(payload.get("title", "")), config_path=config_path, output_root=output_root)
    if job_type == "refresh_all":
        return mirror.execute_gui_action("refresh_all", "", config_path=config_path, output_root=output_root)
    raise ValueError(f"Unsupported job type: {job_type}")


class CircuitBreaker:
    def __init__(self, fail_threshold: int = 3, cooldown_sec: int = 300) -> None:
        self.fail_threshold = fail_threshold
        self.cooldown_sec = cooldown_sec
        self.fail_count = 0
        self.open_until_ts = 0.0

    def is_open(self) -> bool:
        return time.time() < self.open_until_ts

    def record_success(self) -> None:
        self.fail_count = 0
        self.open_until_ts = 0.0

    def record_failure(self) -> bool:
        self.fail_count += 1
        if self.fail_count >= self.fail_threshold:
            self.open_until_ts = time.time() + self.cooldown_sec
            self.fail_count = 0
            return True
        return False


def defer_queued_wikipedia_jobs(conn: sqlite3.Connection, reason: str) -> int:
    now = utc_now()
    ids = [
        int(r["id"])
        for r in conn.execute(
            "SELECT id FROM jobs WHERE status = 'queued' AND type IN ('add_url','mirror_title','mirror_url','refresh_one','refresh_all')"
        ).fetchall()
    ]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"UPDATE jobs SET status = 'deferred', error_text = ? WHERE id IN ({placeholders})", [reason, *ids])
    for job_id in ids:
        conn.execute(
            "INSERT INTO job_events(job_id, level, message, created_at_utc) VALUES (?, 'warn', ?, ?)",
            (job_id, reason, now),
        )
    conn.commit()
    return len(ids)


def release_deferred_jobs(conn: sqlite3.Connection) -> int:
    now = utc_now()
    n = conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'deferred'").rowcount
    if n:
        conn.execute(
            "INSERT INTO audit_events(actor, role, action, target_type, target_ref, result, metadata_json, created_at_utc) VALUES ('system', 'admin', 'jobs.deferred.release', 'job', '*', 'ok', ?, ?)",
            (json.dumps({"count": int(n)}), now),
        )
        conn.commit()
    return int(n or 0)


def cleanup_old_jobs(conn: sqlite3.Connection, days: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cur = conn.execute(
        "DELETE FROM jobs WHERE status IN ('completed','failed','cancelled') AND COALESCE(finished_at_utc, created_at_utc) < ?",
        (cutoff,),
    )
    conn.commit()
    return int(cur.rowcount or 0)


class JobWorker:
    def __init__(self, db_path: Path, config_path: Path, manifest_path: Path, output_root: Path) -> None:
        self.db_path = db_path
        self.config_path = config_path
        self.manifest_path = manifest_path
        self.output_root = output_root
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="archive-job-worker", daemon=True)
        self._breaker = CircuitBreaker(fail_threshold=3, cooldown_sec=300)
        self._last_cleanup_day = ""

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def is_running(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            conn = connect_db(self.db_path)
            try:
                init_db(conn)
                day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if day_key != self._last_cleanup_day:
                    removed = cleanup_old_jobs(conn, int(RUNTIME_SETTINGS.max_jobs_age_days))
                    self._last_cleanup_day = day_key
                    if removed:
                        logger.info("daily cleanup removed %s old jobs", removed)

                if not self._breaker.is_open():
                    released = release_deferred_jobs(conn)
                    if released:
                        logger.info("released %s deferred jobs", released)

                if self._breaker.is_open():
                    time.sleep(0.8)
                    continue

                job = claim_next_job(conn)
                if job is None:
                    time.sleep(0.8)
                    continue

                job_id = int(job["id"])
                payload = json.loads(str(job["payload_json"]))

                try:
                    result_text = perform_job_action(str(job["type"]), payload, self.config_path, self.output_root)
                    conn.execute("UPDATE jobs SET progress = 70 WHERE id = ?", (job_id,))
                    conn.commit()

                    stats = sync_from_files(
                        conn,
                        self.config_path,
                        self.manifest_path,
                        actor=str(job["requested_by"]),
                        role=str(job["requested_role"]),
                    )
                    conn.execute("UPDATE jobs SET progress = 90 WHERE id = ?", (job_id,))
                    conn.commit()

                    audit(
                        conn,
                        actor=str(job["requested_by"]),
                        role=str(job["requested_role"]),
                        action="job.execute",
                        target_type="job",
                        target_ref=str(job_id),
                        result="ok",
                        metadata={"type": job["type"], "sync": stats},
                    )
                    complete_job(conn, job_id, True, {"output": result_text, "sync": stats}, None)
                    self._breaker.record_success()
                except Exception as exc:
                    err_text = str(exc)
                    opened = self._breaker.record_failure()
                    if opened:
                        deferred = defer_queued_wikipedia_jobs(conn, "Wikipedia circuit breaker open for 5 minutes")
                        logger.warning("circuit breaker opened; deferred jobs=%s", deferred)
                    audit(
                        conn,
                        actor=str(job["requested_by"]),
                        role=str(job["requested_role"]),
                        action="job.execute",
                        target_type="job",
                        target_ref=str(job_id),
                        result="failed",
                        metadata={"error": err_text},
                    )
                    if not schedule_job_retry(conn, job_id, err_text, max_retries=3):
                        complete_job(conn, job_id, False, None, err_text)
                    logger.exception("job %s failed", job_id)
            finally:
                conn.close()


def query_items(
    conn: sqlite3.Connection,
    q: str,
    collection: str,
    status: str,
    source: str,
    tag: str,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    clauses: list[str] = []
    params: list[Any] = []

    if q:
        clauses.append(
            "(i.normalized_title IN (SELECT normalized_title FROM item_search WHERE item_search MATCH ?) OR i.title LIKE ? OR i.oldid LIKE ?)"
        )
        params.extend([q, f"%{q}%", f"%{q}%"])
    if collection:
        clauses.append("c.name = ?")
        params.append(collection)
    if status:
        clauses.append("i.status = ?")
        params.append(status)
    else:
        clauses.append("i.status != 'deleted'")
    if source:
        clauses.append("i.source_host = ?")
        params.append(source.lower())
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_id = i.id AND t.name = ?)")
        params.append(tag)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    sort_map = {
        "archived_at": "COALESCE(i.archived_at_utc, i.updated_at_utc)",
        "title": "i.title",
        "size": "COALESCE(i.file_size_bytes, 0)",
    }
    sort_col = sort_map.get(sort, sort_map["archived_at"])
    sort_dir = "ASC" if order.lower() == "asc" else "DESC"

    total = int(
        conn.execute(
            f"SELECT COUNT(*) AS n FROM items i JOIN collections c ON c.id = i.collection_id {where_sql}",
            params,
        ).fetchone()["n"]
    )

    rows = conn.execute(
        f"""
        SELECT
          i.id,
          i.title,
          i.oldid,
          i.source_type,
          i.source_url,
          i.source_host,
          i.status,
          i.archived_at_utc,
          i.output_path,
          i.file_size_bytes,
          i.updated_at_utc,
          c.name AS collection,
          (SELECT GROUP_CONCAT(t.name, ',') FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_id = i.id) AS tags_csv
        FROM items i
        JOIN collections c ON c.id = i.collection_id
        {where_sql}
        ORDER BY {sort_col} {sort_dir}, i.title ASC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        tags_csv = str(item.pop("tags_csv") or "")
        item["tags"] = [t for t in tags_csv.split(",") if t]
        out.append(item)
    return total, out


def query_facets(conn: sqlite3.Connection) -> dict[str, Any]:
    collections = [
        dict(r)
        for r in conn.execute(
            "SELECT c.name, COUNT(i.id) AS count FROM collections c LEFT JOIN items i ON i.collection_id = c.id AND i.status != 'deleted' GROUP BY c.id ORDER BY c.name"
        ).fetchall()
    ]
    statuses = [dict(r) for r in conn.execute("SELECT status AS name, COUNT(*) AS count FROM items WHERE status != 'deleted' GROUP BY status ORDER BY status").fetchall()]
    sources = [
        dict(r)
        for r in conn.execute(
            "SELECT COALESCE(source_host, 'unknown') AS name, COUNT(*) AS count FROM items WHERE status != 'deleted' GROUP BY source_host ORDER BY count DESC, name ASC"
        ).fetchall()
    ]
    tags = [dict(r) for r in conn.execute("SELECT t.name, COUNT(it.item_id) AS count FROM tags t LEFT JOIN item_tags it ON it.tag_id = t.id GROUP BY t.id ORDER BY t.name").fetchall()]
    return {"collections": collections, "statuses": statuses, "sources": sources, "tags": tags}


def query_item_timeline(conn: sqlite3.Connection, title: str, current_item_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, oldid, archived_at_utc, status, output_path, file_size_bytes
        FROM items
        WHERE title = ?
        ORDER BY COALESCE(archived_at_utc, updated_at_utc) DESC, id DESC
        """,
        (title,),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["is_current"] = int(d.get("id", 0)) == int(current_item_id)
        out.append(d)
    return out


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    job["payload"] = json.loads(str(job.pop("payload_json") or "{}"))
    job["result"] = json.loads(str(job.pop("result_json") or "{}")) if job.get("result_json") else None
    job["events"] = [dict(e) for e in conn.execute("SELECT level, message, created_at_utc FROM job_events WHERE job_id = ? ORDER BY id ASC", (job_id,)).fetchall()]
    return job


def create_app(db_path: Path, config_path: Path, manifest_path: Path, output_root: Path):
    from fastapi import FastAPI, HTTPException, Query, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel, Field
    from starlette.responses import JSONResponse
    from typing import Literal

    app = FastAPI(title="Local Mirror Backend", version="0.7.0")
    allowed_origins = [x.strip() for x in RUNTIME_SETTINGS.allowed_origins if str(x).strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    limiter = None
    try:
        from slowapi import Limiter
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
        from slowapi.util import get_remote_address

        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter
        app.add_middleware(SlowAPIMiddleware)

        @app.exception_handler(RateLimitExceeded)
        async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
            return JSONResponse(status_code=429, content={"detail": "Too many login attempts. Try again shortly."})
    except Exception:
        limiter = None

    worker = JobWorker(db_path=db_path, config_path=config_path, manifest_path=manifest_path, output_root=output_root)
    login_limiter = LoginRateLimiter(max_attempts=8, window_sec=60)

    class LoginRequest(BaseModel):
        username: str = Field(min_length=1, max_length=120)
        password: str = Field(min_length=1, max_length=200)
        auth_source: Literal["local", "ad", "auto"] = "auto"

    class ApiKeyLoginRequest(BaseModel):
        username: str = Field(min_length=1, max_length=120)
        api_key: str = Field(min_length=20, max_length=200)

    class UserUpsertRequest(BaseModel):
        username: str = Field(min_length=1, max_length=120)
        role: Literal["viewer", "operator", "admin"]
        display_name: str | None = None
        disabled: bool = False
        password: str | None = Field(default=None, min_length=8, max_length=200)
        auth_source: Literal["local", "ad"] | None = None

    class SaveFilterRequest(BaseModel):
        name: str = Field(min_length=1, max_length=120)
        query: dict[str, Any]

    class ChangePasswordRequest(BaseModel):
        old_password: str = Field(min_length=1, max_length=200)
        new_password: str = Field(min_length=8, max_length=200)

    class ResetPasswordRequest(BaseModel):
        new_password: str = Field(min_length=8, max_length=200)

    class ActionUrlRequest(BaseModel):
        url: str = Field(min_length=1, max_length=500)

    class ActionTitleRequest(BaseModel):
        title: str = Field(min_length=1, max_length=250)

    class ItemDeleteRequest(BaseModel):
        reason: str = Field(min_length=1, max_length=300)

    class ItemTagRequest(BaseModel):
        tag: str = Field(min_length=1, max_length=80)

    class AdminCleanupRequest(BaseModel):
        purge_old_jobs: bool = True
        days: int = Field(default=30, ge=1, le=3650)

    class SettingsRequest(BaseModel):
        settings: dict[str, Any]

    def require_auth(conn: sqlite3.Connection, request: Request, minimum_role: str = "viewer") -> tuple[str, str, dict[str, Any] | None]:
        token = extract_bearer_token(request.headers.get("authorization"))
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        try:
            actor, role, profile = get_actor_from_token(conn, token)
            require_role(role, minimum_role)
            return actor, role, profile
        except PermissionError as exc:
            detail = str(exc)
            status = 403 if "requires" in detail else 401
            raise HTTPException(status_code=status, detail=detail)

    def require_auth_token(conn: sqlite3.Connection, token: str, minimum_role: str = "viewer") -> tuple[str, str, dict[str, Any] | None]:
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        try:
            actor, role, profile = get_actor_from_token(conn, token)
            require_role(role, minimum_role)
            return actor, role, profile
        except PermissionError as exc:
            detail = str(exc)
            status = 403 if "requires" in detail else 401
            raise HTTPException(status_code=status, detail=detail)

    @app.on_event("startup")
    def on_startup() -> None:
        logger.info("backend startup")
        conn = connect_db(db_path)
        try:
            init_db(conn)
            recover_running_jobs(conn)
            sync_from_files(conn, config_path, manifest_path, actor="system", role="admin")
        finally:
            conn.close()
        worker.start()
        logger.info("job worker started")

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        logger.info("backend shutdown")
        worker.stop()

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "time_utc": utc_now(), "version": "0.7.0"}

    @app.post("/api/v1/auth/login")
    @limiter.limit("8/minute") if limiter is not None else (lambda f: f)
    def auth_login(request: Request, payload: LoginRequest) -> dict[str, Any]:
        client_ip = request.client.host if request.client else "unknown"
        if limiter is None and not login_limiter.allow(client_ip):
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again shortly.")

        username = payload.username.strip()
        password = payload.password

        conn = connect_db(db_path)
        try:
            row = conn.execute(
                "SELECT username, role, auth_source, failed_login_count, locked_until_utc, disabled FROM user_profiles WHERE username = ?",
                (username,),
            ).fetchone()

            now = utc_now()
            # Explicit auth_source from client takes priority; fall back to DB record, then AD
            if payload.auth_source in ("local", "ad"):
                source = payload.auth_source
            else:
                source = str(row["auth_source"] if row is not None else "ad")
            ok = False

            if source == "local":
                ok, _ = authenticate_local(conn, username, password)
            else:
                ok, _ = authenticate_ad(username, password)

            if not ok:
                if row is not None:
                    fail = int(row["failed_login_count"] or 0) + 1
                    lock_until = ""
                    if fail >= 5:
                        lock_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    conn.execute(
                        "UPDATE user_profiles SET failed_login_count = ?, locked_until_utc = ?, updated_at_utc = ? WHERE username = ?",
                        (fail, lock_until or None, now, username),
                    )
                    conn.commit()
                raise HTTPException(status_code=401, detail="Invalid credentials")

            if row is None:
                conn.execute(
                    """
                    INSERT INTO user_profiles(username, role, display_name, auth_source, disabled, failed_login_count, created_at_utc, updated_at_utc)
                    VALUES (?, 'viewer', ?, 'ad', 0, 0, ?, ?)
                    """,
                    (username, username, now, now),
                )
            conn.execute(
                "UPDATE user_profiles SET failed_login_count = 0, locked_until_utc = NULL, last_login_utc = ?, updated_at_utc = ? WHERE username = ?",
                (now, now, username),
            )
            token, expires = create_session(conn, username, client_ip, request.headers.get("user-agent"))
            profile = conn.execute(
                "SELECT username, role, display_name, disabled FROM user_profiles WHERE username = ?",
                (username,),
            ).fetchone()
            role = str(profile["role"] if profile is not None else "viewer")
            audit(conn, username, role, "auth.login", "user", username, "ok", {"ip": client_ip})
            conn.commit()
            return {
                "access_token": token,
                "token_type": "bearer",
                "expires_at_utc": expires,
                "actor": username,
                "role": role,
                "capabilities": capability_for_role(role),
            }
        finally:
            conn.close()

    @app.post("/api/v1/auth/logout")
    def auth_logout(request: Request) -> dict[str, Any]:
        token = extract_bearer_token(request.headers.get("authorization"))
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        conn = connect_db(db_path)
        try:
            actor, role, _ = get_actor_from_token(conn, token)
            revoke_session(conn, token)
            audit(conn, actor, role, "auth.logout", "user", actor, "ok", None)
            conn.commit()
            return {"ok": True}
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        finally:
            conn.close()

    @app.post("/api/v1/auth/api-key-login")
    def auth_api_key_login(request: Request, payload: ApiKeyLoginRequest) -> dict[str, Any]:
        client_ip = request.client.host if request.client else "unknown"
        conn = connect_db(db_path)
        try:
            username = payload.username.strip()
            row = conn.execute(
                "SELECT username, role, api_key_hash, disabled FROM user_profiles WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=401, detail="Invalid API key")
            if int(row["disabled"]):
                raise HTTPException(status_code=403, detail="User is disabled")
            expected = str(row["api_key_hash"] or "").strip()
            if not expected or not secrets.compare_digest(expected, sha256_hex(payload.api_key)):
                raise HTTPException(status_code=401, detail="Invalid API key")

            now = utc_now()
            conn.execute(
                "UPDATE user_profiles SET last_login_utc = ?, updated_at_utc = ? WHERE username = ?",
                (now, now, username),
            )
            token, expires = create_session(conn, username, client_ip, request.headers.get("user-agent"))
            role = str(row["role"] or "viewer")
            audit(conn, username, role, "auth.api_key_login", "user", username, "ok", {"ip": client_ip})
            conn.commit()
            return {
                "access_token": token,
                "token_type": "bearer",
                "expires_at_utc": expires,
                "actor": username,
                "role": role,
                "capabilities": capability_for_role(role),
            }
        finally:
            conn.close()

    @app.get("/api/v1/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, profile = require_auth(conn, request, "viewer")
            return {
                "actor": actor,
                "role": role,
                "profile": profile,
                "capabilities": capability_for_role(role),
            }
        finally:
            conn.close()

    @app.post("/api/v1/auth/change-password")
    def auth_change_password(request: Request, payload: ChangePasswordRequest) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "viewer")
            row = conn.execute(
                "SELECT password_hash, auth_source FROM user_profiles WHERE username = ?",
                (actor,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="User profile not found")

            auth_source = str(row["auth_source"] or "local").strip().lower()
            if auth_source != "local":
                raise HTTPException(status_code=400, detail="Password changes are managed by Active Directory for this account")

            current_hash = str(row["password_hash"] or "").strip()
            if not current_hash or not verify_password(payload.old_password, current_hash):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            if payload.old_password == payload.new_password:
                raise HTTPException(status_code=400, detail="New password must be different")

            update_local_password(conn, actor, payload.new_password)
            token = extract_bearer_token(request.headers.get("authorization"))
            if token:
                conn.execute(
                    "UPDATE auth_sessions SET revoked = 1 WHERE username = ? AND token_hash != ?",
                    (actor, sha256_hex(token)),
                )
            audit(conn, actor, role, "auth.password.change", "user", actor, "ok", None)
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/v1/me")
    def me(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, profile = require_auth(conn, request, "viewer")
            return {
                "actor": actor,
                "role": role,
                "profile": profile,
                "capabilities": capability_for_role(role),
            }
        finally:
            conn.close()

    @app.get("/api/v1/me/settings")
    def me_settings(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, _, _ = require_auth(conn, request, "viewer")
            row = conn.execute("SELECT settings_json, updated_at_utc FROM user_settings WHERE username = ?", (actor,)).fetchone()
            if row is None:
                return {"settings": {}, "updated_at_utc": None}
            return {
                "settings": json.loads(str(row["settings_json"] or "{}")),
                "updated_at_utc": row["updated_at_utc"],
            }
        finally:
            conn.close()

    @app.post("/api/v1/me/settings")
    def upsert_me_settings(request: Request, payload: SettingsRequest) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "viewer")
            now = utc_now()
            conn.execute(
                """
                INSERT INTO user_settings(username, settings_json, updated_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET settings_json = excluded.settings_json, updated_at_utc = excluded.updated_at_utc
                """,
                (actor, json.dumps(payload.settings), now),
            )
            audit(conn, actor, role, "me.settings.upsert", "user", actor, "ok", {"keys": sorted(payload.settings.keys())})
            conn.commit()
            return {"ok": True, "updated_at_utc": now}
        finally:
            conn.close()

    @app.post("/api/v1/admin/sync")
    def admin_sync(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")

            stats = sync_from_files(conn, config_path, manifest_path, actor=actor, role=role)
            audit(conn, actor, role, "admin.sync", "library", "global", "ok", stats)
            conn.commit()
            return {"ok": True, "stats": stats}
        finally:
            conn.close()

    @app.get("/api/v1/admin/system")
    def admin_system(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "admin")
            now = utc_now()

            item_total = int(conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"])
            item_status_rows = conn.execute("SELECT status, COUNT(*) AS n FROM items GROUP BY status").fetchall()
            item_status = {str(r["status"]): int(r["n"]) for r in item_status_rows}

            job_total = int(conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])
            job_status_rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
            job_status = {str(r["status"]): int(r["n"]) for r in job_status_rows}

            active_sessions = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM auth_sessions WHERE revoked = 0 AND expires_at_utc > ?",
                    (now,),
                ).fetchone()["n"]
            )
            user_total = int(conn.execute("SELECT COUNT(*) AS n FROM user_profiles").fetchone()["n"])

            last_job_row = conn.execute(
                "SELECT id, type, status, requested_by, created_at_utc, finished_at_utc FROM jobs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            last_job = dict(last_job_row) if last_job_row is not None else None

            db_size_mb = round(db_path.stat().st_size / (1024 * 1024), 2) if db_path.exists() else 0
            max_db_size_mb = int(RUNTIME_SETTINGS.max_db_size_mb)

            return {
                "time_utc": now,
                "worker_running": worker.is_running(),
                "items": {
                    "total": item_total,
                    "archived": item_status.get("archived", 0),
                    "pending": item_status.get("pending", 0),
                    "missing": item_status.get("missing", 0),
                },
                "jobs": {
                    "total": job_total,
                    "queued": job_status.get("queued", 0),
                    "running": job_status.get("running", 0),
                    "failed": job_status.get("failed", 0),
                    "completed": job_status.get("completed", 0),
                    "cancelled": job_status.get("cancelled", 0),
                    "deferred": job_status.get("deferred", 0),
                },
                "users": {
                    "total": user_total,
                    "active_sessions": active_sessions,
                },
                "db": {
                    "size_mb": db_size_mb,
                    "max_size_mb": max_db_size_mb,
                    "warning": db_size_mb > max_db_size_mb,
                },
                "last_job": last_job,
            }
        finally:
            conn.close()

    @app.get("/api/v1/items")
    def list_items_endpoint(
        request: Request,
        q: str = "",
        collection: str = "",
        status: str = "",
        source: str = "",
        tag: str = "",
        sort: str = "archived_at",
        order: str = "desc",
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "viewer")

            total, items = query_items(
                conn,
                q=q.strip(),
                collection=collection.strip(),
                status=status.strip(),
                source=source.strip(),
                tag=tag.strip(),
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
            )
            return {"items": items, "total": total, "limit": limit, "offset": offset, "actor": actor}
        finally:
            conn.close()

    @app.get("/api/v1/items/{item_id}")
    def get_item(item_id: int, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")

            row = conn.execute(
                """
                SELECT i.*, c.name AS collection
                FROM items i
                JOIN collections c ON c.id = i.collection_id
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Item not found")

            item = dict(row)
            item["tags"] = [r["name"] for r in conn.execute("SELECT t.name FROM tags t JOIN item_tags it ON it.tag_id = t.id WHERE it.item_id = ? ORDER BY t.name", (item_id,)).fetchall()]
            item["audit"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT actor, role, action, result, created_at_utc, metadata_json FROM audit_events WHERE target_type = 'item' AND target_ref = ? ORDER BY id DESC LIMIT 25",
                    (str(item_id),),
                ).fetchall()
            ]
            item["timeline"] = query_item_timeline(conn, item["title"], item_id)
            return {"item": item}
        finally:
            conn.close()

    @app.get("/api/v1/items/{item_id}/timeline")
    def item_timeline(item_id: int, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")

            row = conn.execute("SELECT title FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Item not found")
            timeline = query_item_timeline(conn, str(row["title"]), item_id)
            return {"timeline": timeline}
        finally:
            conn.close()

    @app.post("/api/v1/items/{item_id}/tags")
    def add_item_tag(item_id: int, request: Request, payload: ItemTagRequest) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            row = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Item not found")
            tag_name = payload.tag.strip()
            tag_id = ensure_tag(conn, tag_name)
            conn.execute(
                "INSERT OR IGNORE INTO item_tags(item_id, tag_id, created_at_utc) VALUES (?, ?, ?)",
                (item_id, tag_id, utc_now()),
            )
            audit(conn, actor, role, "item.tag.add", "item", str(item_id), "ok", {"tag": tag_name})
            conn.commit()
            return {"ok": True, "tag": tag_name}
        finally:
            conn.close()

    @app.delete("/api/v1/items/{item_id}/tags/{tag}")
    def remove_item_tag(item_id: int, tag: str, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            row = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Item not found")
            conn.execute(
                "DELETE FROM item_tags WHERE item_id = ? AND tag_id IN (SELECT id FROM tags WHERE name = ?)",
                (item_id, tag),
            )
            audit(conn, actor, role, "item.tag.remove", "item", str(item_id), "ok", {"tag": tag})
            conn.commit()
            return {"ok": True, "tag": tag}
        finally:
            conn.close()

    @app.delete("/api/v1/items/{item_id}")
    def delete_item(item_id: int, request: Request, payload: ItemDeleteRequest) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            row = conn.execute("SELECT id, status FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Item not found")
            if str(row["status"] or "") == "deleted":
                raise HTTPException(status_code=409, detail="Item already deleted")
            now = utc_now()
            conn.execute(
                "UPDATE items SET status = 'deleted', deleted_at_utc = ?, deleted_reason = ?, updated_at_utc = ? WHERE id = ?",
                (now, payload.reason.strip(), now, item_id),
            )
            audit(conn, actor, role, "item.delete", "item", str(item_id), "ok", {"reason": payload.reason.strip()})
            conn.commit()
            return {"ok": True, "item_id": item_id, "status": "deleted"}
        finally:
            conn.close()

    @app.get("/api/v1/facets")
    def facets(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")
            return query_facets(conn)
        finally:
            conn.close()

    @app.get("/api/v1/jobs")
    def jobs(request: Request, limit: int = Query(40, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")
            rows: list[dict[str, Any]] = []
            for r in conn.execute(
                "SELECT id, type, status, payload_json, requested_by, requested_role, progress, created_at_utc, started_at_utc, finished_at_utc, error_text FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall():
                job = dict(r)
                job["payload"] = json.loads(str(job.pop("payload_json") or "{}"))
                rows.append(job)
            total = int(conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])
            return {"jobs": rows, "total": total, "limit": limit, "offset": offset}
        finally:
            conn.close()

    @app.get("/api/v1/jobs/{job_id}")
    def job_detail(job_id: int, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")
            job = get_job(conn, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return {"job": job}
        finally:
            conn.close()

    @app.post("/api/v1/jobs/{job_id}/retry")
    def retry_job(job_id: int, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            row = conn.execute("SELECT type, payload_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Job not found")
            new_id = enqueue_job(conn, str(row["type"]), json.loads(str(row["payload_json"])), actor, role)
            return {"ok": True, "job_id": new_id}
        finally:
            conn.close()

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: int, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Job not found")

            status = str(row["status"] or "")
            if status == "queued":
                now = utc_now()
                conn.execute("UPDATE jobs SET status = 'cancelled', progress = 0, finished_at_utc = ?, error_text = NULL WHERE id = ?", (now, job_id))
                conn.execute(
                    "INSERT INTO job_events(job_id, level, message, created_at_utc) VALUES (?, 'warn', ?, ?)",
                    (job_id, f"Job cancelled by {actor}", now),
                )
                audit(conn, actor, role, "job.cancel", "job", str(job_id), "ok", {"previous_status": status})
                conn.commit()
                return {"ok": True, "job_id": job_id, "status": "cancelled"}

            if status == "running":
                raise HTTPException(status_code=409, detail="Job is already running and cannot be cancelled")
            if status in {"completed", "failed", "cancelled"}:
                raise HTTPException(status_code=409, detail=f"Job is already {status}")
            raise HTTPException(status_code=409, detail=f"Job cannot be cancelled from status '{status}'")
        finally:
            conn.close()

    @app.post("/api/v1/jobs/retry-failed")
    def retry_failed_jobs(request: Request, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            rows = conn.execute(
                "SELECT id, type, payload_json FROM jobs WHERE status = 'failed' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            queued = 0
            for row in rows:
                enqueue_job(conn, str(row["type"]), json.loads(str(row["payload_json"])), actor, role)
                queued += 1
            audit(conn, actor, role, "job.retry_failed", "job", "*", "ok", {"queued": queued, "limit": limit})
            conn.commit()
            return {"ok": True, "queued": queued}
        finally:
            conn.close()

    @app.get("/api/v1/jobs/stream")
    @app.get("/api/v1/jobs-sse")
    def jobs_stream(request: Request, token: str = Query("")) -> StreamingResponse:
        conn = connect_db(db_path)
        try:
            auth_token = token or extract_bearer_token(request.headers.get("authorization")) or ""
            require_auth_token(conn, auth_token, "viewer")
        finally:
            conn.close()

        def gen():
            last_sig = ""
            for _ in range(120):
                c = connect_db(db_path)
                try:
                    rows = [
                        dict(r)
                        for r in c.execute(
                            "SELECT id, type, status, progress, requested_by, created_at_utc, started_at_utc, finished_at_utc, error_text FROM jobs ORDER BY id DESC LIMIT 80"
                        ).fetchall()
                    ]
                    sig = json.dumps(rows, sort_keys=True)
                    if sig != last_sig:
                        last_sig = sig
                        yield f"event: jobs\\ndata: {json.dumps({'jobs': rows})}\\n\\n"
                    else:
                        yield "event: ping\\ndata: {}\\n\\n"
                finally:
                    c.close()
                time.sleep(1)

        return StreamingResponse(gen(), media_type="text/event-stream")

    def enqueue_action(request: Request, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "operator")
            job_id = enqueue_job(conn, job_type, payload, actor, role)
            return {"ok": True, "job_id": job_id}
        finally:
            conn.close()

    @app.post("/api/v1/actions/add-url")
    def action_add_url(request: Request, payload: ActionUrlRequest) -> dict[str, Any]:
        return enqueue_action(request, "add_url", {"url": payload.url.strip()})

    @app.post("/api/v1/actions/mirror-one")
    def action_mirror_one(request: Request, payload: ActionTitleRequest) -> dict[str, Any]:
        return enqueue_action(request, "mirror_title", {"title": payload.title.strip()})

    @app.post("/api/v1/actions/mirror-by-url")
    def action_mirror_by_url(request: Request, payload: ActionUrlRequest) -> dict[str, Any]:
        return enqueue_action(request, "mirror_url", {"url": payload.url.strip()})

    @app.post("/api/v1/actions/refresh-one")
    def action_refresh_one(request: Request, payload: ActionTitleRequest) -> dict[str, Any]:
        return enqueue_action(request, "refresh_one", {"title": payload.title.strip()})

    @app.post("/api/v1/actions/refresh-all")
    def action_refresh_all(request: Request) -> dict[str, Any]:
        return enqueue_action(request, "refresh_all", {})

    @app.get("/api/v1/history")
    def history(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")
            rows = [dict(r) for r in conn.execute("SELECT id, actor, role, action, target_type, target_ref, result, metadata_json, created_at_utc FROM audit_events ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()]
            return {"history": rows, "limit": limit, "offset": offset}
        finally:
            conn.close()

    @app.get("/api/v1/history.csv")
    def history_csv(request: Request, limit: int = Query(1000, ge=1, le=5000)) -> Response:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "viewer")
            rows = conn.execute(
                "SELECT id, actor, role, action, target_type, target_ref, result, metadata_json, created_at_utc FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            lines = ["id,actor,role,action,target_type,target_ref,result,created_at_utc,metadata_json"]
            for r in rows:
                vals = [
                    str(r["id"]),
                    str(r["actor"] or ""),
                    str(r["role"] or ""),
                    str(r["action"] or ""),
                    str(r["target_type"] or ""),
                    str(r["target_ref"] or ""),
                    str(r["result"] or ""),
                    str(r["created_at_utc"] or ""),
                    str(r["metadata_json"] or "{}"),
                ]
                escaped = ['"' + v.replace('"', '""') + '"' for v in vals]
                lines.append(",".join(escaped))
            body = "\n".join(lines) + "\n"
            return Response(content=body, media_type="text/csv; charset=utf-8")
        finally:
            conn.close()

    @app.post("/api/v1/admin/cleanup")
    def admin_cleanup(request: Request, payload: AdminCleanupRequest) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")
            removed = 0
            if payload.purge_old_jobs:
                removed = cleanup_old_jobs(conn, payload.days)
            audit(conn, actor, role, "admin.cleanup", "library", "global", "ok", {"removed_jobs": removed, "days": payload.days})
            conn.commit()
            return {"ok": True, "removed_jobs": removed}
        finally:
            conn.close()

    @app.get("/api/v1/saved-filters")
    def saved_filters(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, _, _ = require_auth(conn, request, "viewer")
            rows = [dict(r) for r in conn.execute("SELECT id, owner, name, query_json, created_at_utc, updated_at_utc FROM saved_filters WHERE owner = ? ORDER BY name", (actor,)).fetchall()]
            return {"filters": rows}
        finally:
            conn.close()

    @app.post("/api/v1/saved-filters")
    def save_filter(request: Request, payload: SaveFilterRequest) -> dict[str, Any]:
        name = payload.name.strip()
        query = payload.query

        now = utc_now()
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "viewer")
            conn.execute(
                """
                INSERT INTO saved_filters(owner, name, query_json, created_at_utc, updated_at_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner, name) DO UPDATE SET query_json = excluded.query_json, updated_at_utc = excluded.updated_at_utc
                """,
                (actor, name, json.dumps(query), now, now),
            )
            audit(conn, actor, role, "saved_filter.upsert", "saved_filter", name, "ok", {"query": query})
            conn.commit()
            return {"ok": True, "name": name}
        finally:
            conn.close()

    @app.delete("/api/v1/saved-filters/{name}")
    def delete_filter(name: str, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "viewer")
            conn.execute("DELETE FROM saved_filters WHERE owner = ? AND name = ?", (actor, name))
            audit(conn, actor, role, "saved_filter.delete", "saved_filter", name, "ok", None)
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/v1/admin/users")
    def admin_list_users(request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")

            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT username, role, display_name, disabled, auth_source, last_login_utc, created_at_utc, updated_at_utc FROM user_profiles ORDER BY username"
                ).fetchall()
            ]
            audit(conn, actor, role, "admin.users.list", "user", "*", "ok", None)
            conn.commit()
            return {"users": rows}
        finally:
            conn.close()

    @app.post("/api/v1/admin/users")
    def admin_upsert_user(request: Request, payload: UserUpsertRequest) -> dict[str, Any]:
        username = payload.username.strip()
        role_val = payload.role
        display_name = payload.display_name.strip() if isinstance(payload.display_name, str) and payload.display_name.strip() else None
        disabled = 1 if payload.disabled else 0
        password_hash = hash_password(payload.password) if isinstance(payload.password, str) and payload.password else None

        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")

            now = utc_now()
            existing_row = conn.execute("SELECT auth_source FROM user_profiles WHERE username = ?", (username,)).fetchone()
            auth_source = (payload.auth_source or (str(existing_row["auth_source"]) if existing_row is not None else "local")).strip().lower()
            conn.execute(
                """
                INSERT INTO user_profiles(username, role, display_name, password_hash, auth_source, disabled, created_at_utc, updated_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET role = excluded.role, display_name = excluded.display_name,
                    auth_source = excluded.auth_source,
                    disabled = excluded.disabled, updated_at_utc = excluded.updated_at_utc
                """,
                (username, role_val, display_name, password_hash, auth_source, disabled, now, now),
            )
            if password_hash is not None:
                conn.execute(
                    "UPDATE user_profiles SET password_hash = ?, auth_source = 'local', failed_login_count = 0, locked_until_utc = NULL, updated_at_utc = ? WHERE username = ?",
                    (password_hash, now, username),
                )
            audit(conn, actor, role, "admin.user.upsert", "user", username, "ok", {"role": role_val, "disabled": disabled})
            conn.commit()
            return {"ok": True, "username": username}
        finally:
            conn.close()

    @app.delete("/api/v1/admin/users/{username}")
    def admin_delete_user(username: str, request: Request) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")

            if username == actor:
                raise HTTPException(status_code=400, detail="cannot delete active admin user")

            conn.execute("DELETE FROM user_profiles WHERE username = ?", (username,))
            audit(conn, actor, role, "admin.user.delete", "user", username, "ok", None)
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    @app.post("/api/v1/admin/users/{username}/reset-password")
    def admin_reset_password(username: str, request: Request, payload: ResetPasswordRequest) -> dict[str, Any]:
        target = username.strip()
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")
            row = conn.execute(
                "SELECT username, auth_source FROM user_profiles WHERE username = ?",
                (target,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")

            source = str(row["auth_source"] or "local").strip().lower()
            if source != "local":
                raise HTTPException(status_code=400, detail="Cannot reset password for AD-authenticated account")

            update_local_password(conn, target, payload.new_password)
            conn.execute("UPDATE auth_sessions SET revoked = 1 WHERE username = ?", (target,))
            audit(conn, actor, role, "admin.user.reset_password", "user", target, "ok", None)
            conn.commit()
            return {"ok": True, "username": target}
        finally:
            conn.close()

    @app.post("/api/v1/admin/users/{username}/api-key")
    def admin_issue_api_key(username: str, request: Request) -> dict[str, Any]:
        target = username.strip()
        conn = connect_db(db_path)
        try:
            actor, role, _ = require_auth(conn, request, "admin")
            row = conn.execute("SELECT username FROM user_profiles WHERE username = ?", (target,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")
            api_key = generate_api_key()
            conn.execute(
                "UPDATE user_profiles SET api_key_hash = ?, updated_at_utc = ? WHERE username = ?",
                (sha256_hex(api_key), utc_now(), target),
            )
            audit(conn, actor, role, "admin.user.api_key.issue", "user", target, "ok", None)
            conn.commit()
            return {"ok": True, "username": target, "api_key": api_key}
        finally:
            conn.close()

    @app.get("/api/v1/admin/logs")
    def admin_logs(request: Request, lines: int = Query(200, ge=20, le=2000)) -> dict[str, Any]:
        conn = connect_db(db_path)
        try:
            require_auth(conn, request, "admin")
        finally:
            conn.close()

        log_path = Path(RUNTIME_SETTINGS.log_path)
        if not log_path.exists():
            return {"lines": [], "path": str(log_path), "exists": False}

        data = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"lines": data[-lines:], "path": str(log_path), "exists": True}

    return app


def run_preflight_checks(db_path: Path, config_path: Path, manifest_path: Path, output_root: Path, check_wikipedia: bool = False) -> list[str]:
    problems: list[str] = []
    conn = connect_db(db_path)
    try:
        init_db(conn)
        version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        if version is None or int(version["v"] or 0) < 2:
            problems.append("schema migration version is older than expected")
    finally:
        conn.close()

    for path in [config_path, manifest_path]:
        if not path.exists():
            problems.append(f"missing file: {path}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(f"invalid JSON in {path}: {exc}")

    try:
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / ".write-check.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        problems.append(f"output directory not writable ({output_root}): {exc}")

    if check_wikipedia:
        try:
            import urllib.request

            req = urllib.request.Request("https://en.wikipedia.org/wiki/Main_Page", headers={"User-Agent": "archive-backend-check/1.0"})
            with urllib.request.urlopen(req, timeout=8):
                pass
        except Exception as exc:
            problems.append(f"wikipedia reachability check failed: {exc}")

    return problems


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Archive backend (phases 1-6 consolidated)")
    parser.add_argument("--settings", type=Path, default=Path("config/app.yaml"), help="Path to YAML settings file.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to .env file.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--set-password", nargs=2, metavar=("USERNAME", "PASSWORD"),
                        help="Create or update a local user's password. Use --role to set role (default: admin).")
    parser.add_argument("--promote-user", nargs=2, metavar=("USERNAME", "ROLE"),
                        help="Set an existing user's role. ROLE must be viewer, operator, or admin.")
    parser.add_argument("--test-ad", nargs=2, metavar=("USERNAME", "PASSWORD"),
                        help="Test AD authentication and print the result/error without touching the DB.")
    parser.add_argument("--check", action="store_true", help="Run startup health checks and exit")
    parser.add_argument("--check-wikipedia", action="store_true", help="Include outbound wikipedia reachability check with --check")
    parser.add_argument("--max-jobs-age-days", type=int, default=None, help="Purge completed/failed/cancelled jobs older than this many days")
    parser.add_argument("--max-db-size-mb", type=int, default=None, help="Warning threshold for DB size")
    parser.add_argument("--role", default="admin", choices=["viewer", "operator", "admin"],
                        help="Role for --set-password when creating a new user (default: admin)")
    args = parser.parse_args()

    loaded = load_archive_settings(args.settings, args.env_file)
    loaded.db_path = args.db.resolve() if args.db else Path(loaded.db_path)
    loaded.config_path = args.config.resolve() if args.config else Path(loaded.config_path)
    loaded.manifest_path = args.manifest.resolve() if args.manifest else Path(loaded.manifest_path)
    loaded.output_root = args.output_root.resolve() if args.output_root else Path(loaded.output_root)
    loaded.server_host = args.host or loaded.server_host
    loaded.server_port = int(args.port if args.port is not None else loaded.server_port)
    loaded.max_jobs_age_days = max(1, int(args.max_jobs_age_days if args.max_jobs_age_days is not None else loaded.max_jobs_age_days))
    loaded.max_db_size_mb = max(50, int(args.max_db_size_mb if args.max_db_size_mb is not None else loaded.max_db_size_mb))
    configure_runtime(loaded)
    configure_logging(Path(RUNTIME_SETTINGS.log_path))

    db_path = Path(RUNTIME_SETTINGS.db_path)
    config_path = Path(RUNTIME_SETTINGS.config_path)
    manifest_path = Path(RUNTIME_SETTINGS.manifest_path)
    output_root = Path(RUNTIME_SETTINGS.output_root)

    did_work = False
    conn = connect_db(db_path)
    try:
        init_db(conn)
        recover_running_jobs(conn)

        if args.init_db:
            logger.info("Initialized schema at: %s", db_path.resolve())
            did_work = True

        if args.set_password:
            username, password = args.set_password
            username = username.strip()
            if len(password) < 6:
                logger.error("password must be at least 6 characters")
                return
            now = utc_now()
            existing = conn.execute("SELECT username FROM user_profiles WHERE username = ?", (username,)).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO user_profiles(username, role, display_name, password_hash, auth_source,
                        failed_login_count, disabled, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, 'local', 0, 0, ?, ?)
                    """,
                    (username, args.role, username, hash_password(password), now, now),
                )
                logger.info("Created user '%s' with role '%s'", username, args.role)
            else:
                conn.execute(
                    """
                    UPDATE user_profiles
                    SET password_hash = ?, auth_source = 'local', failed_login_count = 0,
                        locked_until_utc = NULL, updated_at_utc = ?
                    WHERE username = ?
                    """,
                    (hash_password(password), now, username),
                )
                logger.info("Updated password for existing user '%s'", username)
            conn.commit()
            did_work = True

        if args.promote_user:
            username, new_role = args.promote_user
            username = username.strip()
            if new_role not in ("viewer", "operator", "admin"):
                logger.error("role must be viewer, operator, or admin — got '%s'", new_role)
                return
            existing = conn.execute("SELECT role FROM user_profiles WHERE username = ?", (username,)).fetchone()
            if existing is None:
                logger.error("user '%s' not found. They must log in at least once before being promoted.", username)
            else:
                old_role = existing["role"]
                conn.execute(
                    "UPDATE user_profiles SET role = ?, updated_at_utc = ? WHERE username = ?",
                    (new_role, utc_now(), username),
                )
                conn.commit()
                logger.info("Promoted '%s': %s -> %s", username, old_role, new_role)
            did_work = True

        if args.test_ad:
            username, password = args.test_ad
            server_host = RUNTIME_SETTINGS.ad_server
            domain = RUNTIME_SETTINGS.ad_domain
            use_ssl = RUNTIME_SETTINGS.ad_use_ssl
            ntlm_user = f"{domain}\\{username}" if "\\" not in username else username
            upn = username if "@" in username else f"{username}@{domain}"
            logger.info("AD_SERVER  : %s", server_host)
            logger.info("AD_DOMAIN  : %s", domain)
            logger.info("AD_USE_SSL : %s", use_ssl)
            logger.info("NTLM user  : %s", ntlm_user)
            logger.info("UPN        : %s", upn)
            ok, err_msg = authenticate_ad(username, password)
            if ok:
                logger.info("Result     : SUCCESS - credentials accepted")
            else:
                logger.error("Result     : FAILED - %s", err_msg)
            did_work = True

        if args.sync:
            stats = sync_from_files(conn, config_path, manifest_path, actor="cli", role="admin")
            logger.info("Synced from files: %s", stats)
            did_work = True

        if args.stats:
            items = int(conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"])
            collections = int(conn.execute("SELECT COUNT(*) AS n FROM collections").fetchone()["n"])
            jobs = int(conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])
            logger.info("Items: %s", items)
            logger.info("Collections: %s", collections)
            logger.info("Jobs: %s", jobs)
            did_work = True

        if args.check:
            problems = run_preflight_checks(db_path, config_path, manifest_path, output_root, check_wikipedia=args.check_wikipedia)
            db_size_mb = round((db_path.stat().st_size if db_path.exists() else 0) / (1024 * 1024), 2)
            if db_size_mb > RUNTIME_SETTINGS.max_db_size_mb:
                problems.append(f"database size warning: {db_size_mb}MB exceeds threshold {RUNTIME_SETTINGS.max_db_size_mb}MB")
            if problems:
                logger.error("Preflight checks: FAILED")
                for p in problems:
                    logger.error(" - %s", p)
                raise SystemExit(1)
            logger.info("Preflight checks: OK")
            logger.info("DB size: %sMB", db_size_mb)
            did_work = True
    finally:
        conn.close()

    if args.serve:
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit("uvicorn is required for --serve. Install with: pip install uvicorn fastapi") from exc
        app = create_app(db_path, config_path, manifest_path, output_root)
        logger.info("starting uvicorn host=%s port=%s", RUNTIME_SETTINGS.server_host, RUNTIME_SETTINGS.server_port)
        uvicorn.run(app, host=RUNTIME_SETTINGS.server_host, port=RUNTIME_SETTINGS.server_port)
        did_work = True

    if not did_work:
        parser.print_help()


if __name__ == "__main__":
    run_cli()
