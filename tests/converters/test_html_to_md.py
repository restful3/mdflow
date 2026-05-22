from mdflow.converters._html_to_md import html_to_markdown


def test_headings_use_atx_style():
    md = html_to_markdown("<h1>Title</h1><h2>Sub</h2>")
    assert "# Title" in md
    assert "## Sub" in md


def test_bold_and_lists():
    md = html_to_markdown("<p>a <strong>b</strong></p><ul><li>x</li></ul>")
    assert "**b**" in md
    assert "- x" in md or "* x" in md


def test_strip_images_drops_img_tags():
    md = html_to_markdown('<p>t</p><img src="x.png" alt="cat">', strip_images=True)
    assert "![" not in md
    assert "x.png" not in md


def test_keep_images_preserves_alt_by_default():
    md = html_to_markdown('<img src="x.png" alt="cat">')
    assert "cat" in md
