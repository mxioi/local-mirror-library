import mirror_wikipedia_pages as m


def test_generic_title_uses_host_and_path():
    assert m.title_from_generic_url("https://docs.python.org/3/tutorial/index.html") == "docs.python.org/3/tutorial/index"
    assert m.title_from_generic_url("https://docs.python.org/3/tutorial/controlflow.html") == "docs.python.org/3/tutorial/controlflow"


def test_generic_title_distinguishes_index_pages():
    a = m.title_from_generic_url("https://docs.python.org/3/tutorial/index.html")
    b = m.title_from_generic_url("https://docs.python.org/3/library/index.html")
    assert m.normalize_title_key(a) != m.normalize_title_key(b)


def test_generic_title_folder_and_root():
    assert m.title_from_generic_url("https://docs.python.org/3/tutorial/") == "docs.python.org/3/tutorial"
    assert m.title_from_generic_url("https://Example.com/") == "example.com"


def test_generic_title_replaces_unsafe_chars():
    assert m.title_from_generic_url("https://example.com/a b/c%20d.html") == "example.com/a_b/c_d"


def test_slug_is_folder_safe():
    slug = m.slugify("docs.python.org/3/tutorial/index", None)
    assert "/" not in slug and "." not in slug
    assert slug == "docs-python-org-3-tutorial-index"


def test_normalize_page_url():
    n = m.normalize_page_url
    assert n("https://docs.python.org/3/tutorial/index.html") == "docs.python.org/3/tutorial"
    assert n("http://DOCS.python.org/3/tutorial/") == "docs.python.org/3/tutorial"
    assert n("https://docs.python.org/3/tutorial/controlflow.html?x=1#if") == "docs.python.org/3/tutorial/controlflow.html"
    assert n("https://example.com") == "example.com"
