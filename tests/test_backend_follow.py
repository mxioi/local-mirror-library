import json

import archive_backend as a
import mirror_wikipedia_pages as mirror


def test_perform_job_action_passes_follow_options(monkeypatch, tmp_path):
    seen = {}

    def fake(action, value, config_path, output_root, **kwargs):
        seen.update(action=action, value=value, **kwargs)
        return "ok"

    monkeypatch.setattr(mirror, "execute_gui_action", fake)
    a.perform_job_action("add_url", {"url": "https://x/y", "follow_links": True, "link_limit": 5,
                                     "selected_urls": ["https://x/z"]}, tmp_path / "c.json", tmp_path)
    assert seen == {"action": "add_url", "value": "https://x/y", "follow_links": True, "link_limit": 5,
                    "selected_urls": ["https://x/z"]}


def test_perform_job_action_defaults_for_old_payloads(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(mirror, "execute_gui_action", lambda action, value, config_path, output_root, **kw: seen.update(kw) or "ok")
    a.perform_job_action("add_url", {"url": "https://x/y"}, tmp_path / "c.json", tmp_path)
    assert seen == {"follow_links": False, "link_limit": 25, "selected_urls": None}


def test_sync_sets_parent(tmp_path):
    cfg = tmp_path / "pages.json"
    cfg.write_text(json.dumps({"pages": [
        {"title": "docs.python.org/3/tutorial/index", "source_type": "html", "source_url": "https://docs.python.org/3/tutorial/index.html"},
        {"title": "docs.python.org/3/tutorial/appetite", "source_type": "html",
         "source_url": "https://docs.python.org/3/tutorial/appetite.html", "parent": "docs.python.org/3/tutorial/index"},
    ]}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"pages": []}))
    conn = a.connect_db(tmp_path / "t.db")
    a.init_db(conn)
    a.sync_from_files(conn, cfg, manifest)
    rows = {r["title"]: r["parent"] for r in conn.execute("SELECT title, parent FROM items")}
    assert rows == {"docs.python.org/3/tutorial/index": None,
                    "docs.python.org/3/tutorial/appetite": "docs.python.org/3/tutorial/index"}
    total, items = a.query_items(conn, "", "", "", "", "", "title", "asc", 50, 0)
    assert {i["title"]: i["parent"] for i in items}["docs.python.org/3/tutorial/appetite"] == "docs.python.org/3/tutorial/index"
