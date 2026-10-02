import mirror_wikipedia_pages as m

ROOT = {"slug": "docs-python-org-3-tutorial-index", "source_url": "https://docs.python.org/3/tutorial/index.html", "source_type": "html", "oldid": "", "key": "x"}
CHILD = {"slug": "docs-python-org-3-tutorial-appetite", "source_url": "https://docs.python.org/3/tutorial/appetite.html", "source_type": "html", "oldid": "", "key": "y"}
WIKI = {"slug": "Routing-oldid-1", "source_url": "", "source_type": "wikipedia", "oldid": "1", "key": "routing"}


def test_url_lookup_skips_wikipedia_entries():
    lookup = m.build_url_lookup([ROOT, CHILD, WIKI])
    assert set(lookup) == {"docs.python.org/3/tutorial", "docs.python.org/3/tutorial/appetite.html"}


def test_generic_link_points_to_local_copy_with_fragment():
    lookup = m.build_url_lookup([ROOT, CHILD])
    href = m.local_href_for_generic_target("https://docs.python.org/3/tutorial/appetite.html#top", ROOT, lookup)
    assert href == "../docs-python-org-3-tutorial-appetite/index.html#top"


def test_generic_self_link_and_unknown():
    lookup = m.build_url_lookup([ROOT, CHILD])
    assert m.local_href_for_generic_target("https://docs.python.org/3/tutorial/", ROOT, lookup) == "index.html"
    assert m.local_href_for_generic_target("https://docs.python.org/3/library/", ROOT, lookup) is None


def test_rewrite_html_uses_url_lookup():
    lookup = m.build_url_lookup([ROOT, CHILD])
    out = m.rewrite_html('<a href="appetite.html">a</a><a href="../library/">l</a>', ROOT["source_url"], {}, ROOT, {}, url_lookup=lookup)
    assert 'href="../docs-python-org-3-tutorial-appetite/index.html"' in out


def test_rewrite_html_sends_unmirrored_links_to_live_site_but_keeps_anchors():
    lookup = m.build_url_lookup([ROOT, CHILD])
    out = m.rewrite_html('<a href="../library/">l</a><a href="#intro">i</a>', ROOT["source_url"], {}, ROOT, {}, url_lookup=lookup)
    assert 'href="https://docs.python.org/3/library/"' in out
    assert 'href="#intro"' in out
