from mdflow.views.none import synthesize


def test_no_image_refs_unchanged():
    md = "plain markdown\n\nsecond paragraph"
    assert synthesize(md) == md


def test_standalone_image_no_alt_drops_line():
    md = "before\n\n![](figs/abc.png)\n\nafter"
    out = synthesize(md)
    assert "figs/" not in out
    assert "before" in out
    assert "after" in out


def test_standalone_image_with_alt_replaces_with_alt():
    md = "before\n\n![A photo](figs/abc.png)\n\nafter"
    out = synthesize(md)
    assert "figs/" not in out
    assert "A photo" in out


def test_inline_image_with_alt_replaced_by_alt():
    md = "see this ![logo](figs/x.png) here"
    assert synthesize(md) == "see this logo here"


def test_inline_image_no_alt_removed():
    md = "see ![](figs/x.png) end"
    out = synthesize(md)
    assert "figs/" not in out
    assert "see" in out and "end" in out


def test_code_block_refs_protected():
    md = "```md\n![alt](figs/x.png)\n```\n\nbody ![](figs/y.png) end"
    out = synthesize(md)
    assert "![alt](figs/x.png)" in out  # inside code fence — preserved
    assert "figs/y.png" not in out  # outside — removed


def test_collapses_3plus_blank_lines():
    md = "a\n\n\n\n\nb"
    out = synthesize(md)
    assert "\n\n\n" not in out
    assert "a" in out and "b" in out


def test_multiple_images_on_one_line():
    md = "![a](figs/1.png) and ![b](figs/2.png)"
    assert synthesize(md) == "a and b"


def test_non_figs_image_ref_untouched():
    # External URL refs (HTML converter case D7) should pass through
    md = "see ![alt](https://example.com/x.png)"
    assert synthesize(md) == md
