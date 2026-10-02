import io
import json
import urllib.error

import pytest

import mirror_wikipedia_pages as m
from test_follow_flow import ROOT_URL, cfg, fake_web, load  # noqa: F401  (fixtures)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _api(monkeypatch, payload):
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda req, timeout=60: _Resp(json.dumps(payload).encode()))


# Finding 2: Wikipedia links through redirects must resolve to the target article.
def test_wikipedia_redirect_resolves_to_target_title(monkeypatch):
    _api(monkeypatch, {"query": {
        "redirects": [{"from": "BGP", "to": "Border Gateway Protocol"}],
        "pages": {"1": {"title": "Border Gateway Protocol", "revisions": [{"revid": 123}]}},
    }})
    entry = m.resolve_url_entry("https://en.wikipedia.org/wiki/BGP")
    assert entry["title"] == "Border_Gateway_Protocol"
    assert entry["oldid"] == "123"


def test_redirect_child_dedupes_against_existing_target(monkeypatch, tmp_path):
    _api(monkeypatch, {"query": {
        "redirects": [{"from": "BGP", "to": "Border Gateway Protocol"}],
        "pages": {"1": {"title": "Border Gateway Protocol", "revisions": [{"revid": 123}]}},
    }})
    path = tmp_path / "pages.json"
    path.write_text(json.dumps({"pages": [{"title": "Border_Gateway_Protocol", "oldid": "99"}]}))
    assert m.add_child_to_config(path, "https://en.wikipedia.org/wiki/BGP", parent="Routing") == "Border_Gateway_Protocol"
    pages = json.loads(path.read_text())["pages"]
    assert pages == [{"title": "Border_Gateway_Protocol", "oldid": "99"}]


# Finding 3: failures must not leave junk entries in the page config.
def test_wikipedia_child_not_added_when_revision_lookup_fails(monkeypatch, tmp_path):
    def boom(req, timeout=60):
        raise urllib.error.URLError("api down")
    monkeypatch.setattr(m.urllib.request, "urlopen", boom)
    path = tmp_path / "pages.json"
    path.write_text(json.dumps({"pages": []}))
    assert m.add_child_to_config(path, "https://en.wikipedia.org/wiki/Routing", parent="X") is None
    assert json.loads(path.read_text())["pages"] == []


def test_failed_new_child_removed_from_config(fake_web, cfg, tmp_path):
    m.execute_gui_action("add_url", ROOT_URL, cfg, tmp_path / "out", follow_links=True, link_limit=25)
    assert "docs.python.org/3/tutorial/broken" not in load(cfg)


# Finding 4: a pulled-in page must not keep a local link to a sibling that later failed.
def test_sibling_link_to_failed_child_goes_live(fake_web, cfg, tmp_path):
    out = tmp_path / "out"
    m.execute_gui_action("add_url", ROOT_URL, cfg, out, follow_links=True, link_limit=25)
    html = (out / "pages" / "docs-python-org-3-tutorial-appetite" / "index.html").read_text()
    assert 'href="../docs-python-org-3-tutorial-broken/index.html"' not in html
    assert 'href="https://docs.python.org/3/tutorial/broken.html"' in html


# Finding 5: skipped pages are named in the job result.
def test_result_names_skipped_pages(fake_web, cfg, tmp_path):
    msg = m.execute_gui_action("add_url", ROOT_URL, cfg, tmp_path / "out", follow_links=True, link_limit=25)
    assert "docs.python.org/3/tutorial/broken" in msg
