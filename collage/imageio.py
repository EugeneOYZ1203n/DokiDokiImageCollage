"""Image file helpers."""
from __future__ import annotations

import os

from PIL import Image, ImageOps

EXTS = (".png", ".jpg", ".jpeg")


def list_images(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(EXTS)
    )


def open_image(path: str) -> Image.Image:
    """Open with EXIF rotation applied, as RGB."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def open_reduced(path: str, max_side: int) -> tuple[Image.Image, tuple[float, float]]:
    """Open downscaled so longest side <= max_side.

    Returns (image, (fx, fy)) where fx/fy = reduced size / original size per axis.
    """
    ow, oh = image_size(path)
    img = Image.open(path)
    if img.format == "JPEG":
        img.draft("RGB", (max_side, max_side))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img, (img.size[0] / ow, img.size[1] / oh)


def image_size(path: str) -> tuple[int, int]:
    """Size after EXIF orientation, without decoding."""
    with Image.open(path) as im:
        w, h = im.size
        orientation = im.getexif().get(0x0112, 1)
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)
