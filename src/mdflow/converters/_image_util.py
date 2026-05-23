"""Shared helpers for image asset handling.

Content-addressed naming (sha256 of bytes + ext from content-type) gives
mdflow disk-level dedup across documents and converters. canonical_ref
emits the standard `![alt](figs/<name>)` form that view synthesis
modules parse later.
"""

from __future__ import annotations

import hashlib

from mdflow.converters.base import ImageAsset

EXT_BY_CT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}


def content_type_to_ext(content_type: str) -> str:
    return EXT_BY_CT.get(content_type.lower(), "bin")


def sha_filename(data: bytes, content_type: str) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return f"{digest}.{content_type_to_ext(content_type)}"


def make_image_asset(data: bytes, content_type: str) -> ImageAsset:
    return ImageAsset(
        name=sha_filename(data, content_type),
        data=data,
        content_type=content_type,
    )


def canonical_ref(asset: ImageAsset, alt: str = "") -> str:
    return f"![{alt}](figs/{asset.name})"
