import base64

import pytest

from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.views.embed import synthesize


def test_embeds_png_as_data_uri(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "abc.png").write_bytes(b"PNG-DATA")
    md = "before\n![alt](figs/abc.png)\nafter"
    out = synthesize(md, figs)
    b64 = base64.b64encode(b"PNG-DATA").decode("ascii")
    assert f"data:image/png;base64,{b64}" in out
    assert "![alt](data:image/png;base64," in out
    assert "before" in out and "after" in out


def test_no_refs_unchanged(tmp_path):
    assert synthesize("plain text", tmp_path / "figs") == "plain text"


def test_jpeg_mapping(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "x.jpg").write_bytes(b"jpgdata")
    md = "![](figs/x.jpg)"
    out = synthesize(md, figs)
    assert "data:image/jpeg;base64," in out


def test_svg_mapping(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "v.svg").write_bytes(b"<svg/>")
    md = "![](figs/v.svg)"
    out = synthesize(md, figs)
    assert "data:image/svg+xml;base64," in out


def test_gif_mapping(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "g.gif").write_bytes(b"GIF89a")
    md = "![](figs/g.gif)"
    out = synthesize(md, figs)
    assert "data:image/gif;base64," in out


def test_missing_figs_raises_cache_io_error(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    md = "![](figs/missing.png)"
    with pytest.raises(MdflowError) as exc:
        synthesize(md, figs)
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR


def test_code_block_refs_protected(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "x.png").write_bytes(b"d")
    md = "```\n![](figs/x.png)\n```\n\n![](figs/x.png)"
    out = synthesize(md, figs)
    assert "```\n![](figs/x.png)\n```" in out  # code fence untouched
    assert "data:image/png;base64," in out  # body ref embedded


def test_external_url_ref_untouched(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    md = "![alt](https://example.com/x.png)"
    assert synthesize(md, figs) == md
