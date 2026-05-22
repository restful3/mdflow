from mdflow.converters.base import ConversionContext
from mdflow.converters.html import HtmlConverter
from tests.golden import assert_golden


def _ctx(html: str) -> ConversionContext:
    return ConversionContext(data=html.encode("utf-8"), filename_hint="sample.html", format="html")


def test_protocol_attrs():
    conv = HtmlConverter()
    assert conv.name == "html-trafilatura"
    assert conv.formats == ("html",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx("")) is True


def test_html_extracts_body_and_drops_boilerplate(sample_html):
    out = HtmlConverter().convert(_ctx(sample_html), lambda s, p: None)
    md = out.markdown
    assert "Main Heading" in md
    assert "Item one" in md
    assert "Home About Contact" not in md  # nav boilerplate removed
    assert "Copyright 2026" not in md  # footer boilerplate removed
    assert out.metadata["extractor"] == "trafilatura"


def test_html_fallback_when_no_article(sample_html):
    # A bare fragment with no article-like body: trafilatura returns None,
    # so the markdownify fallback runs.
    out = HtmlConverter().convert(_ctx("<div><p>hi</p></div>"), lambda s, p: None)
    assert "hi" in out.markdown
    assert out.metadata["extractor"] == "markdownify-fallback"


def test_html_progress_ends_done(sample_html):
    seen: list[tuple[str, int]] = []
    HtmlConverter().convert(_ctx(sample_html), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_html_golden(sample_html):
    out = HtmlConverter().convert(_ctx(sample_html), lambda s, p: None)
    assert_golden(out.markdown, "html/sample.md")
