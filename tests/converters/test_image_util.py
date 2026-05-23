import hashlib

from mdflow.converters._image_util import (
    EXT_BY_CT,
    canonical_ref,
    content_type_to_ext,
    make_image_asset,
    sha_filename,
)


def test_content_type_to_ext_png():
    assert content_type_to_ext("image/png") == "png"


def test_content_type_to_ext_jpeg():
    assert content_type_to_ext("image/jpeg") == "jpg"


def test_content_type_to_ext_svg():
    assert content_type_to_ext("image/svg+xml") == "svg"


def test_content_type_to_ext_unknown_falls_back_to_bin():
    assert content_type_to_ext("application/octet-stream") == "bin"


def test_content_type_to_ext_case_insensitive():
    assert content_type_to_ext("IMAGE/PNG") == "png"


def test_sha_filename_is_sha256_plus_ext():
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert sha_filename(data, "image/png") == f"{expected}.png"


def test_sha_filename_same_bytes_different_ct_same_digest():
    data = b"x"
    n_png = sha_filename(data, "image/png")
    n_jpg = sha_filename(data, "image/jpeg")
    assert n_png.split(".")[0] == n_jpg.split(".")[0]
    assert n_png.endswith(".png") and n_jpg.endswith(".jpg")


def test_make_image_asset_uses_sha_filename():
    a = make_image_asset(b"data", "image/png")
    assert a.name == sha_filename(b"data", "image/png")
    assert a.data == b"data"
    assert a.content_type == "image/png"


def test_canonical_ref_with_alt():
    a = make_image_asset(b"d", "image/png")
    assert canonical_ref(a, alt="A photo") == f"![A photo](figs/{a.name})"


def test_canonical_ref_no_alt_defaults_to_empty():
    a = make_image_asset(b"d", "image/png")
    assert canonical_ref(a) == f"![](figs/{a.name})"


def test_ext_by_ct_covers_spec_minimum():
    # spec §7.1 enumerates these — exact set guarded
    expected = {"image/png", "image/jpeg", "image/jpg", "image/gif",
                "image/svg+xml", "image/webp", "image/bmp", "image/tiff"}
    assert expected.issubset(EXT_BY_CT.keys())
