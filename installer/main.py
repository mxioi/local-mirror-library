from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd or ROOT), check=True)


def exists(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


def ask(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw or default


def ask_bool(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({suffix}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "1", "true"}


def choose_mode() -> str:
    print("Choose setup mode:")
    print("  1) Python on metal")
    print("  2) Docker Compose")
    print("  3) Kubernetes")
    while True:
        sel = input("Select [1-3]: ").strip()
        if sel == "1":
            return "metal"
        if sel == "2":
            return "compose"
        if sel == "3":
            return "k8s"
        print("Invalid selection.")


def prereq_scan(mode: str) -> list[str]:
    missing: list[str] = []
    if mode == "metal":
        if not exists("python") and not exists("python3"):
            missing.append("python")
    elif mode == "compose":
        if not exists("docker"):
            missing.append("docker")
    elif mode == "k8s":
        if not exists("kubectl"):
            missing.append("kubectl")
        if not exists("docker"):
            missing.append("docker")
    return missing


def write_config(public_host: str, api_port: int, web_port: int, use_ad: bool, ad_server: str, ad_domain: str, ad_ssl: bool) -> None:
    config_dir = ROOT / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    bind_host = "0.0.0.0"

    app_yaml = f"""paths:
  db: wikipedia-local/library.db
  config: wikipedia-pages.json
  manifest: wikipedia-local/manifest.json
  output_root: wikipedia-local
  log: wikipedia-local/archive.log

server:
  host: {bind_host}
  port: {api_port}
  library_port: {web_port}
  library_home_url: http://{public_host}:{web_port}/Local%20Mirror%20Library.html
  allowed_origins:
    - http://localhost:{web_port}
    - http://127.0.0.1:{web_port}
    - http://{public_host}:{web_port}

auth:
  session_hours: 12
  bootstrap_admin_password: ""
  ad_server: {ad_server}
  ad_domain: {ad_domain}
  ad_use_ssl: {str(ad_ssl).lower()}

limits:
  max_jobs_age_days: 30
  max_db_size_mb: 500
"""

    env_text = f"""ARCHIVE_HOST={bind_host}
ARCHIVE_PORT={api_port}
ARCHIVE_LIBRARY_PORT={web_port}
ALLOWED_ORIGINS=http://localhost:{web_port},http://127.0.0.1:{web_port},http://{public_host}:{web_port}
AD_SERVER={ad_server}
AD_DOMAIN={ad_domain}
AD_USE_SSL={1 if ad_ssl else 0}
"""
    (config_dir / "app.yaml").write_text(app_yaml, encoding="utf-8")
    (ROOT / ".env").write_text(env_text, encoding="utf-8")

    output_root = ROOT / "wikipedia-local"
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text('{"pages": []}\n', encoding="utf-8")

    if not use_ad:
        print("AD auth disabled by installer choice; local auth still available.")


def setup_metal() -> None:
    py = "python" if exists("python") else "python3"
    venv = ROOT / ".venv"
    if not venv.exists():
        run([py, "-m", "venv", ".venv"])
    python_bin = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    run([python_bin, "-m", "pip", "install", "--upgrade", "pip"])
    run([python_bin, "-m", "pip", "install", "-r", "requirements.txt"])
    run([python_bin, "archive_backend.py", "--check", "--settings", "config/app.yaml", "--env-file", ".env"])
    print("Metal install complete.")
    print(f"Run API: {python_bin} archive_backend.py --serve --settings config/app.yaml --env-file .env")
    print(f"Run UI : {python_bin} -m http.server 8080")


def setup_compose() -> None:
    run(["docker", "compose", "build"])
    run(["docker", "compose", "up", "-d"])
    print("Docker Compose install complete.")
    print("Check status: docker compose ps")
    print("Logs: docker compose logs -f")


def setup_k8s() -> None:
    run(["docker", "build", "-t", "local-mirror:latest", "."])
    run(["kubectl", "apply", "-f", "k8s/namespace.yaml"])
    run(["kubectl", "apply", "-f", "k8s/configmap.yaml"])
    run(["kubectl", "apply", "-f", "k8s/secret.yaml"])
    run(["kubectl", "apply", "-f", "k8s/pvc.yaml"])
    run(["kubectl", "apply", "-f", "k8s/deployment.yaml"])
    run(["kubectl", "apply", "-f", "k8s/service.yaml"])
    print("Kubernetes install complete.")
    print("Check: kubectl -n local-mirror get pods,svc")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Mirror onboarding installer")
    parser.add_argument("--mode", choices=["metal", "compose", "k8s"], default=None)
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    mode = args.mode or choose_mode()

    with ThreadPoolExecutor(max_workers=1) as ex:
        scan_future = ex.submit(prereq_scan, mode)

        default_host = socket.gethostbyname(socket.gethostname())
        host = default_host if args.non_interactive else ask("Server host/IP", default_host)
        api_port = int("8010" if args.non_interactive else ask("Backend API port", "8010"))
        web_port = int("8080" if args.non_interactive else ask("Frontend web port", "8080"))
        use_ad = True if args.non_interactive else ask_bool("Enable AD authentication", True)
        ad_server = "ad.example.local" if args.non_interactive else ask("AD server hostname", "ad.example.local")
        ad_domain = "example.local" if args.non_interactive else ask("AD domain", "example.local")
        ad_ssl = False if args.non_interactive else ask_bool("Use LDAPS (SSL)", False)

        missing = scan_future.result()

    if missing:
        print("Missing required tools:", ", ".join(missing))
        print("Install prerequisites and re-run installer.")
        raise SystemExit(2)

    write_config(host, api_port, web_port, use_ad, ad_server, ad_domain, ad_ssl)

    if mode == "metal":
        setup_metal()
    elif mode == "compose":
        setup_compose()
    else:
        setup_k8s()

    print(f"API health URL: http://{host}:{api_port}/api/v1/health")
    print(f"UI URL: http://{host}:{web_port}/Local%20Mirror%20Library.html")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInstaller cancelled.")
        sys.exit(130)
