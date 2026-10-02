import json
import urllib.error

import pytest

import mirror_wikipedia_pages as m

ROOT_URL = "https://docs.python.org/3/tutorial/index.html"
PAGES = {
    ROOT_URL: '<div><a href="appetite.html">a</a> <a href="interpreter.html">i</a> <a href="broken.html">b</a></div>',
    "https://docs.python.org/3/tutorial/appetite.html": '<a href="index.html">back</a> <a href="interpreter.html">i</a> <a href="deeper.html">d</a> <a href="broken.html">b</a>',
    "https://docs.python.org/3/tutorial/interpreter.html": "<p>interp</p>",
}


@pytest.fixture
def fake_web(monkeypatch):
    def fetch(url):
        if url in PAGES:
            return PAGES[url].encode(), "text/html"
        raise urllib.error.URLError(f"no route: {url}")
    monkeypatch.setattr(m, "fetch_with_type", fetch)


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "pages.json"
    path.write_text(json.dumps({"pages": []}))
    return path


def load(cfg):
    return {p["title"]: p for p in json.loads(cfg.read_text())["pages"]}


def test_follow_adds_children_one_level(fake_web, cfg, tmp_path):
    msg = m.execute_gui_action("add_url", ROOT_URL, cfg, tmp_path / "out", follow_links=True, link_limit=25)
    pages = load(cfg)
    root = pages["docs.python.org/3/tutorial/index"]
    assert root["follow_links"] is True and root["link_limit"] == 25
    child = pages["docs.python.org/3/tutorial/appetite"]
    assert child["parent"] == "docs.python.org/3/tutorial/index"
    assert child["follow_links"] is False
    assert "docs.python.org/3/tutorial/deeper" not in pages  # never follows the child's links
    assert "1 skipped" in msg


def test_failed_child_is_skipped_and_root_links_live(fake_web, cfg, tmp_path):
    out = tmp_path / "out"
    m.execute_gui_action("add_url", ROOT_URL, cfg, out, follow_links=True, link_limit=25)
    root_html = (out / "pages" / "docs-python-org-3-tutorial-index" / "index.html").read_text()
    assert 'href="../docs-python-org-3-tutorial-appetite/index.html"' in root_html
    assert 'href="../docs-python-org-3-tutorial-broken/index.html"' not in root_html
    assert 'href="https://docs.python.org/3/tutorial/broken.html"' in root_html
    assert not (out / "pages" / "docs-python-org-3-tutorial-broken" / "index.html").exists()
    child_html = (out / "pages" / "docs-python-org-3-tutorial-appetite" / "index.html").read_text()
    assert 'href="../docs-python-org-3-tutorial-index/index.html"' in child_html


def test_existing_page_not_duplicated_or_reparented(fake_web, cfg, tmp_path):
    cfg.write_text(json.dumps({"pages": [
        {"title": "docs.python.org/3/tutorial/index", "oldid": "", "source_type": "html", "source_url": ROOT_URL},
        {"title": "docs.python.org/3/tutorial/interpreter", "oldid": "", "source_type": "html",
         "source_url": "https://docs.python.org/3/tutorial/interpreter.html", "parent": "someone-else"},
    ]}))
    m.execute_gui_action("add_url", ROOT_URL, cfg, tmp_path / "out", follow_links=True, link_limit=25)
    raw = json.loads(cfg.read_text())["pages"]
    titles = [p["title"] for p in raw]
    assert titles.count("docs.python.org/3/tutorial/index") == 1
    assert titles.count("docs.python.org/3/tutorial/interpreter") == 1
    assert load(cfg)["docs.python.org/3/tutorial/interpreter"]["parent"] == "someone-else"


def test_selected_urls_only(fake_web, cfg, tmp_path):
    m.execute_gui_action("add_url", ROOT_URL, cfg, tmp_path / "out", follow_links=True,
                         selected_urls=["https://docs.python.org/3/tutorial/interpreter.html", "https://evil.example/x"])
    pages = load(cfg)
    assert "docs.python.org/3/tutorial/interpreter" in pages
    assert "docs.python.org/3/tutorial/appetite" not in pages
    assert not any("evil" in t for t in pages)


def test_follow_off_is_unchanged_behaviour(fake_web, cfg, tmp_path):
    m.execute_gui_action("add_url", ROOT_URL, cfg, tmp_path / "out")
    assert list(load(cfg)) == ["docs.python.org/3/tutorial/index"]


def test_preview_follow_links(fake_web):
    links = m.preview_follow_links(ROOT_URL)
    assert [l["title"] for l in links] == [
        "docs.python.org/3/tutorial/appetite",
        "docs.python.org/3/tutorial/interpreter",
        "docs.python.org/3/tutorial/broken",
    ]
