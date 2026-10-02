import mirror_wikipedia_pages as m

WIKI_URL = "https://en.wikipedia.org/wiki/Border_Gateway_Protocol"
WIKI_HTML = """
<div id="mw-navigation"><a href="/wiki/Main_Page">Main</a></div>
<div id="mw-content-text">
  <p><a href="/wiki/Routing">Routing</a>
     <a href="/wiki/Autonomous_system_(Internet)">AS</a>
     <a href="/wiki/Autonomous_system_%28Internet%29#History">AS again</a>
     <a href="/wiki/Help:IPA">help</a> <a href="/wiki/File:BGP.png">file</a>
     <a href="/wiki/Talk:Routing">talk</a> <a href="/wiki/Category:Protocols">cat</a>
     <a href="/wiki/Star_Wars:_Episode_IV">colon article</a>
     <a href="/wiki/Border_Gateway_Protocol#Operation">self</a>
     <a class="new" href="/w/index.php?title=Missing&amp;action=edit&amp;redlink=1">red</a>
     <a href="https://www.cisco.com/x">external</a></p>
  <h2 id="References">References</h2>
  <p><a href="/wiki/After_References">after</a></p>
</div>
"""


def titles(links):
    return [l["title"] for l in links]


def test_wikipedia_body_article_links_only_in_order():
    links = m.extract_follow_links(WIKI_HTML, WIKI_URL, "wikipedia")
    assert titles(links) == ["Routing", "Autonomous_system_(Internet)", "Star_Wars:_Episode_IV"]
    assert links[0]["url"] == "https://en.wikipedia.org/wiki/Routing"


def test_wikipedia_without_content_div_uses_whole_page():
    links = m.extract_follow_links('<a href="/wiki/Routing">r</a>', WIKI_URL, "wikipedia")
    assert titles(links) == ["Routing"]


GEN_URL = "https://docs.python.org/3/tutorial/index.html"
GEN_HTML = """
<nav><a href="whatnow.html">nav link</a></nav>
<div class="body">
  <a href="appetite.html">Whetting</a>
  <a href="interpreter.html#using">Interpreter</a>
  <a href="appetite.html">dup</a>
  <a href="controlflow.html?highlight=x">Control</a>
  <a href="../library/index.html">library</a>
  <a href="https://www.python.org/">python.org</a>
  <a href="_images/pic.png">image</a> <a href="files/tut.pdf">pdf</a>
  <a href="index.html">self</a> <a href="#top">anchor</a>
  <a href="sub/">subfolder</a>
</div>
"""


def test_generic_same_section_only():
    links = m.extract_follow_links(GEN_HTML, GEN_URL, "html")
    assert [l["url"] for l in links] == [
        "https://docs.python.org/3/tutorial/appetite.html",
        "https://docs.python.org/3/tutorial/interpreter.html",
        "https://docs.python.org/3/tutorial/controlflow.html",
        "https://docs.python.org/3/tutorial/sub/",
    ]
    assert links[0]["title"] == "docs.python.org/3/tutorial/appetite"


def test_generic_folder_url_start():
    links = m.extract_follow_links('<a href="appetite.html">a</a><a href="/3/library/">l</a>',
                                   "https://docs.python.org/3/tutorial/", "html")
    assert [l["url"] for l in links] == ["https://docs.python.org/3/tutorial/appetite.html"]


CANDS = [{"url": f"https://example.com/d/p{i}.html", "title": f"example.com/d/p{i}"} for i in range(150)]


def test_choose_links_first_n_and_clamp():
    assert len(m.choose_links(CANDS, 25, None)) == 25
    assert len(m.choose_links(CANDS, 0, None)) == 1
    assert len(m.choose_links(CANDS, 500, None)) == 100


def test_choose_links_selected_ignores_unknown_urls():
    picked = m.choose_links(CANDS, 25, ["https://example.com/d/p3.html", "https://evil.example/x", "https://example.com/d/p1.html#frag"])
    assert [p["url"] for p in picked] == ["https://example.com/d/p1.html", "https://example.com/d/p3.html"]
