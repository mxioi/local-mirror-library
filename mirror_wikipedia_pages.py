import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import html
import io
import mimetypes
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from settings import load_archive_settings


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_CONFIG_PATH = Path("wikipedia-pages.json")
DEFAULT_OUTPUT_ROOT = Path("wikipedia-local")
DEFAULT_LIBRARY_HOME_URL = "http://localhost:8080/Local%20Mirror%20Library.html"


def fetch_with_type(url: str) -> tuple[bytes, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read(), resp.headers.get("Content-Type")


def guess_extension(url: str, content_type: str | None) -> str:
    parsed = urllib.parse.urlparse(url)
    ext = Path(parsed.path).suffix
    if ext:
        return ext

    if content_type:
        ct = content_type.lower().split(";")[0].strip()
        if ct == "text/css":
            return ".css"
        if ct in ("application/javascript", "text/javascript"):
            return ".js"
        if ct == "image/svg+xml":
            return ".svg"
        if ct == "image/png":
            return ".png"
        if ct == "image/jpeg":
            return ".jpg"
        if ct == "image/webp":
            return ".webp"
        if ct == "font/woff2":
            return ".woff2"
        if ct == "font/woff":
            return ".woff"

    return ".bin"


def asset_filename(url: str, content_type: str | None, forced_ext: str | None = None) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = forced_ext or guess_extension(url, content_type)
    return f"{digest}{ext}"


def normalize_url(base_url: str, raw: str) -> str:
    raw = html.unescape(raw.strip())
    if not raw or raw.startswith("data:"):
        return ""
    return urllib.parse.urljoin(base_url, raw)


def normalize_title_key(title: str) -> str:
    title = urllib.parse.unquote(title).strip().replace(" ", "_")
    return title.casefold()


def extract_wikipedia_target(url: str) -> tuple[str | None, str | None, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc and parsed.netloc != "en.wikipedia.org":
        return None, None, ""

    title: str | None = None
    oldid: str | None = None
    if parsed.path.startswith("/wiki/"):
        title = parsed.path[len("/wiki/") :]
    elif parsed.path == "/w/index.php":
        query = urllib.parse.parse_qs(parsed.query)
        title_values = query.get("title")
        oldid_values = query.get("oldid")
        if title_values:
            title = title_values[0]
        if oldid_values:
            oldid = oldid_values[0]

    if not title:
        return None, None, ""

    return urllib.parse.unquote(title).replace(" ", "_"), oldid, parsed.fragment


def extract_stylesheet_urls(html_text: str, base_url: str) -> set[str]:
    urls: set[str] = set()
    for m in re.finditer(r'<link[^>]+rel=["\'][^"\']*stylesheet[^"\']*["\'][^>]*>', html_text, re.I):
        tag = m.group(0)
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if not href:
            continue
        resolved = normalize_url(base_url, href.group(1))
        if resolved:
            urls.add(resolved)
    return urls


def extract_image_urls(html_text: str, base_url: str) -> set[str]:
    urls: set[str] = set()

    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_text, re.I):
        resolved = normalize_url(base_url, m.group(1))
        if resolved:
            urls.add(resolved)

    for m in re.finditer(r'srcset=["\']([^"\']+)["\']', html_text, re.I):
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        for part in parts:
            candidate = part.split()[0]
            resolved = normalize_url(base_url, candidate)
            if resolved:
                urls.add(resolved)

    return urls


def clean_generic_html(html_text: str) -> str:
    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html_text)
    cleaned = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", "", cleaned)
    cleaned = re.sub(r"(?is)<(nav|header|footer|aside)[^>]*>.*?</\1>", "", cleaned)
    return cleaned


def extract_css_urls(css_text: str, css_url: str) -> set[str]:
    urls: set[str] = set()
    for m in re.finditer(r'url\(([^)]+)\)', css_text, re.I):
        raw = m.group(1).strip().strip('"\'')
        resolved = normalize_url(css_url, raw)
        if resolved:
            urls.add(resolved)
    return urls


def rewrite_css(css_text: str, css_url: str, mapping: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(1).strip().strip('"\'')
        resolved = normalize_url(css_url, raw)
        if resolved in mapping:
            return f'url("{mapping[resolved]}")'
        return match.group(0)

    return re.sub(r'url\(([^)]+)\)', repl, css_text, flags=re.I)


def local_href_for_wikipedia_target(
    resolved_url: str,
    current_page: dict[str, str],
    local_page_lookup: dict[str, list[dict[str, str]]],
) -> str | None:
    title, target_oldid, fragment = extract_wikipedia_target(resolved_url)
    if not title:
        return None

    key = normalize_title_key(title)
    candidates = local_page_lookup.get(key) or []
    if not candidates:
        return None

    target = candidates[0]
    if target_oldid:
        for cand in candidates:
            if str(cand.get("oldid", "")) == str(target_oldid):
                target = cand
                break

    if target["slug"] == current_page["slug"]:
        return f"#{fragment}" if fragment else "index.html"

    href = f"../{target['slug']}/index.html"
    if fragment:
        href += f"#{fragment}"
    return href


def rewrite_html(
    html_text: str,
    base_url: str,
    mapping: dict[str, str],
    current_page: dict[str, str],
    local_page_lookup: dict[str, list[dict[str, str]]],
) -> str:
    def replace_attr(match: re.Match[str]) -> str:
        attr = match.group(1)
        value = match.group(2)
        resolved = normalize_url(base_url, value)

        if resolved in mapping:
            return f'{attr}="{mapping[resolved]}"'

        if attr.lower() == "href":
            local_href = local_href_for_wikipedia_target(
                resolved_url=resolved,
                current_page=current_page,
                local_page_lookup=local_page_lookup,
            )
            if local_href:
                return f'{attr}="{local_href}"'

            parsed = urllib.parse.urlparse(resolved)
            if parsed.netloc == "en.wikipedia.org" and (
                parsed.path.startswith("/wiki/") or parsed.path == "/w/index.php"
            ):
                return f'{attr}="{resolved}"'

        return match.group(0)

    html_text = re.sub(r'(href|src)=["\']([^"\']+)["\']', replace_attr, html_text, flags=re.I)

    def replace_srcset(match: re.Match[str]) -> str:
        value = match.group(1)
        parts = [p.strip() for p in value.split(",") if p.strip()]
        rewritten: list[str] = []

        for part in parts:
            tokens = part.split()
            if not tokens:
                continue
            resolved = normalize_url(base_url, tokens[0])
            if resolved in mapping:
                tokens[0] = mapping[resolved]
            rewritten.append(" ".join(tokens))

        return f'srcset="{", ".join(rewritten)}"'

    return re.sub(r'srcset=["\']([^"\']+)["\']', replace_srcset, html_text, flags=re.I)


def build_navigation_overlay(current_page: dict[str, str], pages: list[dict[str, str]], library_home_url: str) -> str:
    timeline_pages = [p for p in pages if p["key"] == current_page["key"]]
    timeline_pages.sort(key=lambda p: str(p.get("oldid", "")), reverse=True)

    lines: list[str] = [
        "<style id=\"local-mirror-nav-style\">",
        "#local-mirror-nav { position: fixed; right: 12px; bottom: 12px; z-index: 99999; font-family: sans-serif; }",
        "#local-mirror-nav details { background: #fff; border: 1px solid #a2a9b1; border-radius: 6px; box-shadow: 0 2px 12px rgba(0,0,0,0.2); }",
        "#local-mirror-nav summary { cursor: pointer; font-size: 14px; padding: 8px 10px; font-weight: 600; }",
        "#local-mirror-nav .panel { padding: 0 10px 10px 10px; max-height: 260px; overflow: auto; min-width: 240px; }",
        "#local-mirror-nav .home { display: inline-block; margin-bottom: 8px; }",
        "#local-mirror-nav ul { margin: 0; padding-left: 18px; }",
        "#local-mirror-nav li { margin: 4px 0; font-size: 13px; }",
        "#local-mirror-nav li.current { font-weight: 700; }",
        "</style>",
        "<div id=\"local-mirror-nav\">",
        "  <details>",
        "    <summary>Page timeline</summary>",
        "    <div class=\"panel\">",
        f"      <a class=\"home\" href=\"{html.escape(library_home_url)}\">Library home</a>",
        "      <ul>",
    ]

    for page in timeline_pages:
        label = page["title"]
        if page.get("oldid"):
            label = f"oldid {page['oldid']}"
        else:
            label = "latest"

        if page["slug"] == current_page["slug"]:
            lines.append(f"        <li class=\"current\">{html.escape(label)}</li>")
            continue

        href = f"../{page['slug']}/index.html"
        lines.append(f"        <li><a href=\"{href}\">{html.escape(label)}</a></li>")

    lines += [
        "      </ul>",
        "    </div>",
        "  </details>",
        "</div>",
    ]

    return "\n".join(lines)


def inject_navigation_overlay(
    html_text: str,
    current_page: dict[str, str],
    pages: list[dict[str, str]],
    library_home_url: str,
) -> str:
    overlay = build_navigation_overlay(current_page=current_page, pages=pages, library_home_url=library_home_url)
    if re.search(r"</body>", html_text, flags=re.I):
        return re.sub(r"</body>", overlay + "\n</body>", html_text, count=1, flags=re.I)
    return html_text + "\n" + overlay + "\n"


def slugify(title: str, oldid: str | None) -> str:
    base = title.strip().replace(" ", "_")
    base = re.sub(r"[^A-Za-z0-9_\-]", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    if oldid:
        return f"{base}-oldid-{oldid}"
    return base


def build_source_url(title: str, oldid: str | None) -> str:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    if oldid:
        return f"https://en.wikipedia.org/w/index.php?title={encoded}&oldid={oldid}"
    return f"https://en.wikipedia.org/wiki/{encoded}"


def infer_source_type_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith("wikipedia.org"):
        return "wikipedia"
    if host.endswith("rfc-editor.org"):
        return "rfc"
    return "html"


def title_from_generic_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return parsed.netloc or "remote-page"
    name = path.split("/")[-1] or parsed.netloc or "remote-page"
    name = urllib.parse.unquote(name)
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    name = re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_")
    return name or "remote-page"


def extract_title_oldid_from_url(url: str) -> tuple[str, str | None]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "en.m.wikipedia.org":
        host = "en.wikipedia.org"
    if host != "en.wikipedia.org":
        raise ValueError("Only en.wikipedia.org URLs are supported.")

    title: str | None = None
    oldid: str | None = None

    if parsed.path.startswith("/wiki/"):
        title = parsed.path[len("/wiki/") :]
    elif parsed.path == "/w/index.php":
        query = urllib.parse.parse_qs(parsed.query)
        title_values = query.get("title")
        oldid_values = query.get("oldid")
        if title_values:
            title = title_values[0]
        if oldid_values:
            oldid = oldid_values[0]
    else:
        raise ValueError("URL must be /wiki/<Title> or /w/index.php?title=... form.")

    if not title:
        raise ValueError("Could not extract article title from URL.")

    title = urllib.parse.unquote(title).replace(" ", "_").strip()
    if not title:
        raise ValueError("Extracted title is empty.")

    if oldid is not None:
        oldid = oldid.strip()
        if oldid and not re.fullmatch(r"\d+", oldid):
            raise ValueError("oldid in URL must be numeric.")
        if not oldid:
            oldid = None

    return title, oldid


def fetch_latest_oldid(title: str) -> str:
    api_url = (
        "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=ids&titles="
        f"{urllib.parse.quote(title, safe='')}&format=json"
    )
    req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    pages = payload.get("query", {}).get("pages", {})
    if not isinstance(pages, dict) or not pages:
        raise ValueError(f"Could not resolve oldid for title: {title}")

    page = next(iter(pages.values()))
    revisions = page.get("revisions")
    if not revisions or not isinstance(revisions, list):
        raise ValueError(f"No revisions found for title: {title}")

    revid = revisions[0].get("revid")
    if revid is None:
        raise ValueError(f"No revid found for title: {title}")
    return str(revid)


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {"pages": []}
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"pages": raw}
    if isinstance(raw, dict):
        pages = raw.get("pages")
        if pages is None:
            raw["pages"] = []
            return raw
        if isinstance(pages, list):
            return raw
    raise ValueError("Config must be an object with a 'pages' list or a raw list of page entries.")


def save_config(config_path: Path, config: dict) -> None:
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def upsert_page_config_entry(
    config: dict,
    title: str,
    oldid: str,
    update_existing: bool,
) -> tuple[str, dict]:
    pages = config.setdefault("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Config 'pages' must be a list.")

    new_key = normalize_title_key(title)
    for item in pages:
        if not isinstance(item, dict):
            continue
        existing_title = str(item.get("title", ""))
        if normalize_title_key(existing_title) != new_key:
            continue

        changed = False
        if existing_title != title:
            item["title"] = title
            changed = True
        existing_oldid = str(item.get("oldid", "")).strip()
        if update_existing and existing_oldid != oldid:
            item["oldid"] = oldid
            changed = True
        return ("updated" if changed else "unchanged", item)

    new_item = {"title": title, "oldid": oldid}
    pages.append(new_item)
    return "added", new_item


def add_url_to_config(config_path: Path, url: str, update_existing: bool) -> tuple[str, str, str]:
    try:
        title, oldid = extract_title_oldid_from_url(url)
        source_type = "wikipedia"
        source_url = ""
        if not oldid:
            oldid = fetch_latest_oldid(title)
    except Exception:
        title = title_from_generic_url(url)
        oldid = None
        source_type = infer_source_type_from_url(url)
        source_url = url

    config = load_config(config_path)
    action, _ = upsert_page_config_entry(
        config=config,
        title=title,
        oldid=oldid or "",
        update_existing=update_existing,
    )
    pages = config.get("pages", []) if isinstance(config, dict) else []
    if isinstance(pages, list):
        key = normalize_title_key(title)
        for item in pages:
            if isinstance(item, dict) and normalize_title_key(str(item.get("title", ""))) == key:
                item["source_type"] = source_type
                if source_url:
                    item["source_url"] = source_url
                break
    save_config(config_path, config)
    return action, title, oldid or ""


def refresh_config_oldids(config_path: Path) -> int:
    config = load_config(config_path)
    pages = config.get("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Config 'pages' must be a list.")

    updates = 0
    for item in pages:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip().replace(" ", "_")
        if not title:
            continue
        if str(item.get("source_type", "wikipedia")).strip().lower() != "wikipedia":
            continue
        latest = fetch_latest_oldid(title)
        current = str(item.get("oldid", "")).strip()
        if current != latest:
            item["oldid"] = latest
            updates += 1

    save_config(config_path, config)
    return updates


def refresh_config_oldids_for_keys(config_path: Path, title_keys: set[str] | None) -> int:
    config = load_config(config_path)
    pages = config.get("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Config 'pages' must be a list.")

    updates = 0
    for item in pages:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip().replace(" ", "_")
        if not title:
            continue
        key = normalize_title_key(title)
        if title_keys is not None and key not in title_keys:
            continue
        if str(item.get("source_type", "wikipedia")).strip().lower() != "wikipedia":
            continue
        latest = fetch_latest_oldid(title)
        current = str(item.get("oldid", "")).strip()
        if current != latest:
            item["oldid"] = latest
            updates += 1

    save_config(config_path, config)
    return updates


def build_page_entries(page_specs: list[dict[str, str]]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    used_slugs: set[str] = set()

    for spec in page_specs:
        title = spec["title"]
        oldid = spec.get("oldid")
        key = normalize_title_key(title)

        base_slug = slugify(title, oldid)
        slug = base_slug
        index = 2
        while slug in used_slugs:
            slug = f"{base_slug}-v{index}"
            index += 1
        used_slugs.add(slug)

        entry = {
            "title": title,
            "oldid": oldid or "",
            "slug": slug,
            "key": key,
            "output_rel": f"pages/{slug}/index.html",
            "collection": spec.get("collection") or "Wikipedia",
            "source_type": spec.get("source_type") or "wikipedia",
            "source_url": spec.get("source_url") or "",
        }
        entries.append(entry)

    return entries


def build_page_lookup(entries: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    lookup: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        lookup.setdefault(entry["key"], []).append(entry)

    for _, group in lookup.items():
        group.sort(key=lambda p: str(p.get("oldid", "")), reverse=True)

    return lookup


def mirror_page(
    page: dict[str, str],
    output_root: Path,
    all_pages: list[dict[str, str]],
    local_page_lookup: dict[str, list[dict[str, str]]],
    library_home_url: str,
) -> dict[str, str]:
    title = page["title"]
    oldid = page["oldid"] or None
    source_type = str(page.get("source_type") or "wikipedia").strip().lower() or "wikipedia"
    source_url = str(page.get("source_url") or "").strip() or build_source_url(title, oldid)
    page_dir = output_root / "pages" / page["slug"]
    assets_dir = page_dir / "assets"
    page_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    html_data, _ = fetch_with_type(source_url)
    html_text = html_data.decode("utf-8", errors="replace")
    if source_type in {"html", "rfc"}:
        html_text = clean_generic_html(html_text)

    mapping: dict[str, str] = {}
    css_sources: list[str] = []

    stylesheet_urls = extract_stylesheet_urls(html_text, source_url)
    image_urls = extract_image_urls(html_text, source_url)
    first_pass_urls = sorted(stylesheet_urls | image_urls)

    for url in first_pass_urls:
        try:
            data, content_type = fetch_with_type(url)
        except Exception:
            continue

        forced_ext = ".css" if url in stylesheet_urls else None
        name = asset_filename(url, content_type, forced_ext=forced_ext)
        rel = f"assets/{name}"
        (page_dir / rel).write_bytes(data)
        mapping[url] = rel

        if rel.endswith(".css"):
            css_sources.append(url)

    css_asset_urls: set[str] = set()
    css_text_map: dict[str, str] = {}

    for css_url in css_sources:
        rel = mapping.get(css_url)
        if not rel:
            continue
        css_path = page_dir / rel
        try:
            css_text = css_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        css_text_map[css_url] = css_text
        css_asset_urls.update(extract_css_urls(css_text, css_url))

    for url in sorted(css_asset_urls):
        if url in mapping:
            continue
        try:
            data, content_type = fetch_with_type(url)
        except Exception:
            continue

        name = asset_filename(url, content_type)
        rel = f"assets/{name}"
        (page_dir / rel).write_bytes(data)
        mapping[url] = rel

    for css_url, css_text in css_text_map.items():
        rel = mapping.get(css_url)
        if not rel:
            continue
        rewritten_css = rewrite_css(css_text, css_url, mapping)
        (page_dir / rel).write_text(rewritten_css, encoding="utf-8")

    rewritten_html = rewrite_html(
        html_text=html_text,
        base_url=source_url,
        mapping=mapping,
        current_page=page,
        local_page_lookup=local_page_lookup,
    )
    rewritten_html = inject_navigation_overlay(
        html_text=rewritten_html,
        current_page=page,
        pages=all_pages,
        library_home_url=library_home_url,
    )
    (page_dir / "index.html").write_text(rewritten_html, encoding="utf-8")

    return {
        "title": title,
        "oldid": oldid or "",
        "source_type": source_type,
        "source_url": source_url,
        "output": str((output_root / page["output_rel"]).as_posix()),
    }


def load_page_specs(config_path: Path) -> list[dict[str, str]]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    page_specs: list[dict[str, str]] = []

    items = raw.get("pages") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Config must be a list or an object with a 'pages' list.")

    for item in items:
        if not isinstance(item, dict) or "title" not in item:
            raise ValueError("Each page item must be an object containing at least 'title'.")

        title = str(item["title"]).strip().replace(" ", "_")
        oldid_value = item.get("oldid")
        oldid = str(oldid_value).strip() if oldid_value is not None and str(oldid_value).strip() else None
        collection = str(item.get("collection", "Wikipedia")).strip() or "Wikipedia"
        source_type = str(item.get("source_type", "wikipedia")).strip().lower() or "wikipedia"
        source_url = str(item.get("source_url", "")).strip()
        page_specs.append(
            {
                "title": title,
                "oldid": oldid or "",
                "collection": collection,
                "source_type": source_type,
                "source_url": source_url,
            }
        )

    return page_specs


def load_existing_manifest_map(output_root: Path) -> dict[str, dict[str, str]]:
    manifest_path = output_root / "manifest.json"
    if not manifest_path.exists():
        return {}

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    items = payload.get("pages", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return {}

    existing: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        existing[normalize_title_key(title)] = item
    return existing


def write_root_index(output_root: Path, pages: list[dict[str, str]]) -> None:
    rows: list[dict[str, str]] = []
    for page in pages:
        rel = Path(page["output"]).relative_to(output_root).as_posix()
        rows.append(
            {
                "title": page.get("title", ""),
                "oldid": page.get("oldid", ""),
                "collection": page.get("collection", "Wikipedia"),
                "archived_at_utc": page.get("archived_at_utc", ""),
                "source_url": page.get("source_url", ""),
                "href": rel,
            }
        )

    data_json = json.dumps(rows, ensure_ascii=True)

    html_text = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Local Mirror Library</title>
  <style>
    :root {{
      --bg: #f2efe8;
      --panel: #fffdf8;
      --text: #1e2228;
      --muted: #5a6675;
      --line: #d7d2c5;
      --brand: #0f5d63;
      --chip: #ebf3f4;
      --accent: #f6e6bd;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--text);
      background: radial-gradient(circle at 18% 8%, #fff7dc 0%, var(--bg) 55%);
    }}
    .wrap {{ max-width: 1240px; margin: 0 auto; padding: 24px 16px 48px; }}
    .hero {{
      background: linear-gradient(145deg, #fffdf8 0%, #f8f3e8 100%);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 3px 14px rgba(40, 35, 20, 0.08);
    }}
    .title {{ margin: 0 0 8px; font-size: 34px; line-height: 1.1; }}
    .subtitle {{ margin: 0; color: var(--muted); font-size: 16px; }}
    .controls {{ display: grid; gap: 10px; grid-template-columns: 1fr 220px; margin-top: 16px; }}
    .input, .select, .button {{
      width: 100%;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
      font-family: inherit;
    }}
    .button {{ cursor: pointer; background: #f3efe6; }}
    .button:hover {{ background: #ece6d7; }}
    .meta {{ margin-top: 12px; color: var(--muted); font-size: 14px; }}
    .layout {{ margin-top: 16px; display: grid; gap: 14px; grid-template-columns: 260px 1fr; align-items: start; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; box-shadow: 0 2px 8px rgba(35,31,22,.05); }}
    .panel h2 {{ margin: 0 0 10px; font-size: 18px; }}
    .facet-list, .command-list {{ margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }}
    .facet-btn {{ width: 100%; text-align: left; border: 1px solid var(--line); background: #fff; border-radius: 8px; padding: 8px 9px; cursor: pointer; }}
    .facet-btn.active {{ background: var(--accent); border-color: #cfb167; }}
    .facet-count {{ float: right; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 2px 8px rgba(35, 31, 22, 0.05);
    }}
    .card h3 {{ margin: 0 0 8px; font-size: 19px; line-height: 1.25; }}
    .chip {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      background: var(--chip);
      border: 1px solid #c9dde0;
      color: #0c4a4f;
      font-size: 12px;
      margin-right: 6px;
      margin-bottom: 5px;
    }}
    .row {{ margin-top: 8px; color: var(--muted); font-size: 13px; }}
    .actions {{ margin-top: 12px; display: flex; gap: 12px; font-size: 14px; flex-wrap: wrap; }}
    .cmd-title {{ font-weight: 700; margin-top: 12px; margin-bottom: 4px; font-size: 14px; }}
    .cmd-row {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; }}
    .status {{ margin-top: 8px; padding: 8px; border: 1px dashed var(--line); border-radius: 8px; color: var(--muted); font-size: 13px; white-space: pre-wrap; }}
    a {{ color: var(--brand); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty {{ margin-top: 18px; color: var(--muted); display: none; }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .controls {{ grid-template-columns: 1fr; }}
      .title {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <section class=\"hero\">
      <h1 class=\"title\">Local Archive Library</h1>
      <p class=\"subtitle\">Search, browse, and manage your locally mirrored pages.</p>
      <div class=\"controls\">
        <input id=\"search\" class=\"input\" type=\"search\" placeholder=\"Search title, oldid, collection, host\" autocomplete=\"off\">
        <select id=\"collection\" class=\"select\"></select>
      </div>
      <div id=\"meta\" class=\"meta\"></div>
    </section>
    <section class=\"layout\">
      <aside>
        <div class=\"panel\">
          <h2>Collections</h2>
          <div id=\"facetList\" class=\"facet-list\"></div>
        </div>
        <div class=\"panel\" style=\"margin-top:12px\">
          <h2>Archive Actions</h2>
          <div class=\"cmd-title\">Add URL + mirror only added</div>
          <div class=\"cmd-row\"><input id=\"cmdAddUrl\" class=\"input\" placeholder=\"https://en.wikipedia.org/wiki/Example\"><button class=\"button\" data-action=\"add_url\">Run</button></div>
          <div class=\"cmd-title\">Mirror only title</div>
          <div class=\"cmd-row\"><input id=\"cmdOnlyTitle\" class=\"input\" placeholder=\"Domain_Name_System\"><button class=\"button\" data-action=\"only_title\">Run</button></div>
          <div class=\"cmd-title\">Mirror only URL</div>
          <div class=\"cmd-row\"><input id=\"cmdOnlyUrl\" class=\"input\" placeholder=\"https://en.wikipedia.org/wiki/IPv4\"><button class=\"button\" data-action=\"only_url\">Run</button></div>
          <div class=\"cmd-title\">Refresh one + mirror one</div>
          <div class=\"cmd-row\"><input id=\"cmdRefreshOne\" class=\"input\" placeholder=\"IPv4\"><button class=\"button\" data-action=\"refresh_one\">Run</button></div>
          <div class=\"cmd-title\">Refresh all + mirror all</div>
          <div class=\"cmd-row\"><button class=\"button\" data-action=\"refresh_all\">Run full update</button></div>
          <div id=\"cmdStatus\" class=\"status\">Tip: run this page via `python mirror_wikipedia_pages.py --serve` to enable action buttons.</div>
        </div>
      </aside>
      <section>
        <section id=\"grid\" class=\"grid\"></section>
        <p id=\"empty\" class=\"empty\">No matches for the current search/filter.</p>
      </section>
    </section>
  </main>
  <script>
    const DATA = {data_json};
    const searchEl = document.getElementById('search');
    const collectionEl = document.getElementById('collection');
    const metaEl = document.getElementById('meta');
    const gridEl = document.getElementById('grid');
    const emptyEl = document.getElementById('empty');
    const facetListEl = document.getElementById('facetList');
    const cmdStatusEl = document.getElementById('cmdStatus');

    let activeFacet = 'All collections';

    function hostFrom(url) {{
      try {{ return new URL(url).host; }} catch (e) {{ return ''; }}
    }}

    function collectionLink(name) {{
      const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      return `collections/${{slug || 'collection'}}/index.html`;
    }}

    function formatDate(iso) {{
      if (!iso) return 'not mirrored yet';
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toLocaleString();
    }}

    const collectionMap = DATA.reduce((acc, p) => {{
      const c = p.collection || 'Wikipedia';
      acc[c] = (acc[c] || 0) + 1;
      return acc;
    }}, {{}});
    const collections = ['All collections', ...Object.keys(collectionMap).sort()];
    collectionEl.innerHTML = collections.map(c => `<option value="${{c}}">${{c}}</option>`).join('');

    function renderFacets() {{
      const buttons = collections.map(c => {{
        const count = c === 'All collections' ? DATA.length : (collectionMap[c] || 0);
        const active = c === activeFacet ? 'active' : '';
        const browse = c === 'All collections' ? '' : `<a href="${{collectionLink(c)}}" style="margin-left:8px">Open</a>`;
        return `<button class="facet-btn ${{active}}" data-facet="${{c}}">${{c}} <span class="facet-count">${{count}}</span></button>${{browse}}`;
      }}).join('');
      facetListEl.innerHTML = buttons;
      Array.from(facetListEl.querySelectorAll('button[data-facet]')).forEach(btn => {{
        btn.addEventListener('click', () => {{
          activeFacet = btn.dataset.facet || 'All collections';
          collectionEl.value = activeFacet;
          render();
        }});
      }});
    }}

    function render() {{
      const q = searchEl.value.trim().toLowerCase();
      const selected = collectionEl.value;
      activeFacet = selected;
      renderFacets();

      const filtered = DATA
        .filter(p => selected === 'All collections' || (p.collection || 'Wikipedia') === selected)
        .filter(p => {{
          if (!q) return true;
          const title = (p.title || '').toLowerCase().replace(/_/g, ' ');
          const oldid = (p.oldid || '').toLowerCase();
          const host = hostFrom(p.source_url).toLowerCase();
          const collection = (p.collection || '').toLowerCase();
          return title.includes(q) || oldid.includes(q) || host.includes(q) || collection.includes(q);
        }})
        .sort((a, b) => (b.archived_at_utc || '').localeCompare(a.archived_at_utc || ''));

      metaEl.textContent = `${{filtered.length}} shown / ${{DATA.length}} total`;

      gridEl.innerHTML = filtered.map(p => `
        <article class="card">
          <h3><a href="${{p.href}}">${{p.title}}</a></h3>
          <div>
            <span class="chip">${{p.collection || 'Wikipedia'}}</span>
            <span class="chip">oldid ${{p.oldid || 'latest'}}</span>
          </div>
          <div class="row">Archived: ${{formatDate(p.archived_at_utc)}}</div>
          <div class="row">Source: ${{hostFrom(p.source_url)}}</div>
          <div class="actions">
            <a href="${{p.href}}">Open local</a>
            <a href="${{p.source_url}}" target="_blank" rel="noopener">Open source</a>
            <a href="${{collectionLink(p.collection || 'Wikipedia')}}">Collection page</a>
          </div>
        </article>
      `).join('');

      emptyEl.style.display = filtered.length ? 'none' : 'block';
    }}

    async function runAction(action, value) {{
      cmdStatusEl.textContent = 'Running...';
      try {{
        const response = await fetch('/api/run', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ action, value }}),
        }});
        const payload = await response.json();
        cmdStatusEl.textContent = payload.ok ? payload.output : `Error: ${{payload.error || 'unknown error'}}`;
        if (payload.ok) {{
          setTimeout(() => window.location.reload(), 350);
        }}
      }} catch (err) {{
        cmdStatusEl.textContent = 'Action API unavailable. Start with: python mirror_wikipedia_pages.py --serve';
      }}
    }}

    function wireActionButtons() {{
      const getVal = (id) => (document.getElementById(id)?.value || '').trim();
      Array.from(document.querySelectorAll('button[data-action]')).forEach(btn => {{
        btn.addEventListener('click', () => {{
          const action = btn.dataset.action;
          if (action === 'add_url') return runAction('add_url', getVal('cmdAddUrl'));
          if (action === 'only_title') return runAction('only_title', getVal('cmdOnlyTitle'));
          if (action === 'only_url') return runAction('only_url', getVal('cmdOnlyUrl'));
          if (action === 'refresh_one') return runAction('refresh_one', getVal('cmdRefreshOne'));
          if (action === 'refresh_all') return runAction('refresh_all', '');
        }});
      }});
    }}

    searchEl.addEventListener('input', render);
    collectionEl.addEventListener('change', render);
    wireActionButtons();
    render();
  </script>
</body>
</html>
"""

    (output_root / "index.html").write_text(html_text, encoding="utf-8")


def collection_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "collection"


def write_collection_indexes(output_root: Path, pages: list[dict[str, str]]) -> None:
    grouped: dict[str, list[dict[str, str]]] = {}
    for page in pages:
        collection = page.get("collection", "Wikipedia") or "Wikipedia"
        grouped.setdefault(collection, []).append(page)

    root = output_root / "collections"
    root.mkdir(parents=True, exist_ok=True)

    for collection, items in grouped.items():
        slug = collection_slug(collection)
        col_dir = root / slug
        col_dir.mkdir(parents=True, exist_ok=True)

        cards: list[str] = []
        for page in sorted(items, key=lambda p: (p.get("title", "").lower())):
            target = Path(page["output"]).resolve()
            rel = Path(os.path.relpath(str(target), start=str(col_dir.resolve()))).as_posix()
            oldid = page.get("oldid", "") or "latest"
            archived = page.get("archived_at_utc", "")
            cards.append(
                f"<li><a href=\"{html.escape(rel)}\">{html.escape(page.get('title', 'Untitled'))}</a> "
                f"<span>(oldid {html.escape(oldid)})</span> <small>{html.escape(archived)}</small></li>"
            )

        page_html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{title}</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 0; background: #f2efe8; color: #1e2228; }}
    .wrap {{ max-width: 880px; margin: 0 auto; padding: 24px 16px; }}
    .panel {{ background: #fffdf8; border: 1px solid #d7d2c5; border-radius: 10px; padding: 16px; }}
    a {{ color: #0f5d63; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    ul {{ line-height: 1.8; }}
    small {{ color: #5a6675; margin-left: 6px; }}
    span {{ color: #5a6675; margin-left: 6px; }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <div class=\"panel\">
      <p><a href=\"../../index.html\">Back to library</a></p>
      <h1>{title}</h1>
      <ul>
        {items}
      </ul>
    </div>
  </main>
</body>
</html>
""".format(title=html.escape(collection), items="\n        ".join(cards))

        (col_dir / "index.html").write_text(page_html, encoding="utf-8")


def run_mirror(
    config_path: Path,
    output_root: Path,
    clean: bool,
    only_title_keys: set[str] | None,
    library_home_url: str,
) -> None:
    page_specs = load_page_specs(config_path)
    all_pages = build_page_entries(page_specs)
    local_page_lookup = build_page_lookup(all_pages)

    selected_pages = all_pages
    if only_title_keys is not None:
        selected_pages = [page for page in all_pages if page["key"] in only_title_keys]
        missing = sorted(k for k in only_title_keys if k not in local_page_lookup)
        if missing:
            raise ValueError(f"Requested page(s) not found in config: {', '.join(missing)}")

    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    existing_manifest = load_existing_manifest_map(output_root)
    run_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    mirrored_keys = {page["key"] for page in selected_pages}

    for page in selected_pages:
        oldid = page["oldid"]
        print(f"Mirroring: {page['title']}" + (f" (oldid {oldid})" if oldid else ""))
        mirror_page(
            page=page,
            output_root=output_root,
            all_pages=all_pages,
            local_page_lookup=local_page_lookup,
            library_home_url=library_home_url,
        )

    manifest: list[dict[str, str]] = []
    for page in all_pages:
        oldid = page["oldid"] or ""
        key = page["key"]
        existing = existing_manifest.get(key, {})
        archived_at_utc = run_timestamp if key in mirrored_keys else str(existing.get("archived_at_utc", ""))
        manifest.append(
            {
                "title": page["title"],
                "oldid": oldid,
                "collection": page.get("collection", "Wikipedia"),
                "source_type": page.get("source_type", "wikipedia"),
                "source_url": str(page.get("source_url") or "").strip() or build_source_url(page["title"], oldid or None),
                "output": str((output_root / page["output_rel"]).as_posix()),
                "archived_at_utc": archived_at_utc,
            }
        )

    (output_root / "manifest.json").write_text(
        json.dumps({"pages": manifest}, indent=2),
        encoding="utf-8",
    )
    write_root_index(output_root, manifest)
    write_collection_indexes(output_root, manifest)

    print(f"Saved mirrors to: {output_root.resolve()}")
    print("Serve locally with: python -m http.server 8080")


def execute_gui_action(
    action: str,
    value: str,
    config_path: Path,
    output_root: Path,
    library_home_url: str = DEFAULT_LIBRARY_HOME_URL,
) -> str:
    value = value.strip()

    if action == "add_url":
        if not value:
            raise ValueError("URL is required.")
        _, title, _ = add_url_to_config(config_path=config_path, url=value, update_existing=True)
        run_mirror(
            config_path=config_path,
            output_root=output_root,
            clean=False,
            only_title_keys={normalize_title_key(title)},
            library_home_url=library_home_url,
        )
        return f"Added/updated and mirrored: {title}"

    if action == "only_title":
        if not value:
            raise ValueError("Title is required.")
        run_mirror(
            config_path=config_path,
            output_root=output_root,
            clean=False,
            only_title_keys={normalize_title_key(value)},
            library_home_url=library_home_url,
        )
        return f"Mirrored page title: {value}"

    if action == "only_url":
        if not value:
            raise ValueError("URL is required.")
        _, title, _ = add_url_to_config(config_path=config_path, url=value, update_existing=True)
        run_mirror(
            config_path=config_path,
            output_root=output_root,
            clean=False,
            only_title_keys={normalize_title_key(title)},
            library_home_url=library_home_url,
        )
        return f"Mirrored page URL title: {title}"

    if action == "refresh_one":
        if not value:
            raise ValueError("Title is required.")
        key = normalize_title_key(value)
        refresh_config_oldids_for_keys(config_path=config_path, title_keys={key})
        run_mirror(
            config_path=config_path,
            output_root=output_root,
            clean=False,
            only_title_keys={key},
            library_home_url=library_home_url,
        )
        return f"Refreshed oldid and mirrored: {value}"

    if action == "refresh_all":
        refresh_config_oldids_for_keys(config_path=config_path, title_keys=None)
        run_mirror(
            config_path=config_path,
            output_root=output_root,
            clean=False,
            only_title_keys=None,
            library_home_url=library_home_url,
        )
        return "Refreshed all oldids and mirrored all pages."

    raise ValueError(f"Unknown action: {action}")


def start_control_server(
    output_root: Path,
    config_path: Path,
    port: int,
    library_home_url: str = DEFAULT_LIBRARY_HOME_URL,
) -> None:
    output_root = output_root.resolve()
    config_path = config_path.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_file(self, rel_path: str) -> None:
            clean = rel_path.split("?", 1)[0].split("#", 1)[0]
            clean = clean.lstrip("/") or "index.html"
            target = (output_root / clean).resolve()

            if not str(target).startswith(str(output_root)):
                self.send_error(403)
                return

            if target.is_dir():
                target = target / "index.html"
            if not target.exists() or not target.is_file():
                self.send_error(404)
                return

            data = target.read_bytes()
            ctype, _ = mimetypes.guess_type(str(target))
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype or 'application/octet-stream'}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._serve_file(self.path)

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/api/run":
                self.send_error(404)
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8", errors="replace"))
                action = str(payload.get("action", ""))
                value = str(payload.get("value", ""))

                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    result = execute_gui_action(
                        action=action,
                        value=value,
                        config_path=config_path,
                        output_root=output_root,
                        library_home_url=library_home_url,
                    )
                output = capture.getvalue().strip()
                if output:
                    output = output + "\n" + result
                else:
                    output = result
                self._send_json(200, {"ok": True, "output": output})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("", port), Handler)
    print(f"Control server running at: http://localhost:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mirror one or more Wikipedia pages for local serving without crawling linked pages."
    )
    parser.add_argument("--settings", type=Path, default=Path("config/app.yaml"), help="Path to YAML settings file.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to .env file.")
    parser.add_argument("--config", type=Path, default=None, help="Path to page config JSON.")
    parser.add_argument("--output-root", type=Path, default=None, help="Output directory root.")
    parser.add_argument(
        "--library-home-url",
        default=None,
        help="URL used by mirrored page overlay 'Library home' link.",
    )
    parser.add_argument("--clean", action="store_true", help="Delete output root before mirroring.")
    parser.add_argument(
        "--only-title",
        action="append",
        default=[],
        help="Mirror/update only specific page title(s) from config. Repeat as needed.",
    )
    parser.add_argument(
        "--only-url",
        action="append",
        default=[],
        help="Mirror/update only specific page URL(s) from config. Repeat as needed.",
    )
    parser.add_argument(
        "--add-url",
        action="append",
        default=[],
        help="Add an en.wikipedia.org page URL to config and auto-resolve oldid. Repeat for multiple URLs.",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="When used with --add-url/--refresh-oldids, skip mirroring run.",
    )
    parser.add_argument(
        "--refresh-oldids",
        action="store_true",
        help="Update all config entries to latest oldid before mirroring.",
    )
    parser.add_argument(
        "--keep-existing-oldid",
        action="store_true",
        help="With --add-url, do not overwrite oldid if the page already exists in config.",
    )
    parser.add_argument(
        "--mirror-added-only",
        action="store_true",
        help="With --add-url, mirror only URLs added/updated in this run instead of all pages.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the local library UI with action API enabled.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for --serve mode (default: 8080).",
    )
    args = parser.parse_args()

    loaded = load_archive_settings(args.settings, args.env_file)
    config_path = args.config.resolve() if args.config else Path(loaded.config_path)
    output_root = args.output_root.resolve() if args.output_root else Path(loaded.output_root)
    library_home_url = args.library_home_url or loaded.library_home_url or DEFAULT_LIBRARY_HOME_URL
    serve_port = int(args.port if args.port is not None else loaded.library_port)

    touched_config = False
    added_request_keys: set[str] = set()

    for raw_url in args.add_url:
        action, title, oldid = add_url_to_config(
            config_path=config_path,
            url=raw_url,
            update_existing=not args.keep_existing_oldid,
        )
        print(f"Config {action}: {title}" + (f" (oldid {oldid})" if oldid else ""))
        touched_config = True
        added_request_keys.add(normalize_title_key(title))

    requested_only_keys: set[str] = set()
    for title in args.only_title:
        requested_only_keys.add(normalize_title_key(title))
    for raw_url in args.only_url:
        _, title, _ = add_url_to_config(
            config_path=config_path,
            url=raw_url,
            update_existing=not args.keep_existing_oldid,
        )
        requested_only_keys.add(normalize_title_key(title))

    refresh_scope: set[str] | None = requested_only_keys if requested_only_keys else None

    if args.refresh_oldids:
        updates = refresh_config_oldids_for_keys(config_path, refresh_scope)
        print(f"Refreshed oldids in config: {updates} updated")
        touched_config = True

    mirror_scope: set[str] | None = None
    if requested_only_keys:
        mirror_scope = set(requested_only_keys)
    if args.mirror_added_only and added_request_keys:
        mirror_scope = set(added_request_keys)

    should_mirror = not args.no_mirror
    if should_mirror:
        run_mirror(
            config_path=config_path,
            output_root=output_root,
            clean=args.clean,
            only_title_keys=mirror_scope,
            library_home_url=library_home_url,
        )
    elif touched_config:
        print(f"Config updated at: {config_path.resolve()}")

    if args.serve:
        start_control_server(
            output_root=output_root,
            config_path=config_path,
            port=serve_port,
            library_home_url=library_home_url,
        )


if __name__ == "__main__":
    main()
