"""Compose the collage."""
from __future__ import annotations

import logging
import math
from typing import Callable

from PIL import Image

from .crop import CropBox, centered_box
from .imageio import open_image
from .models import LabelledTemplate

log = logging.getLogger(__name__)

# path -> (image, (fx, fy)) where fx/fy = loaded size / original size
ImageGetter = Callable[[str], tuple[Image.Image, tuple[float, float]]]


def _full(path: str) -> tuple[Image.Image, tuple[float, float]]:
    return open_image(path), (1.0, 1.0)


def safe_source_box(box: CropBox, img: Image.Image, f: tuple[float, float], out_size: tuple[int, int]) -> tuple[float, float, float, float]:
    """Crop box (original-image px) -> box inside `img` that Pillow will accept.

    Guards float overshoot at the edges and invalid boxes (falls back to a centred crop).
    """
    iw, ih = img.size
    if box.is_finite():
        x0, y0 = box.x * f[0], box.y * f[1]
        x1, y1 = (box.x + box.w) * f[0], (box.y + box.h) * f[1]
        x0, x1 = min(max(x0, 0.0), iw), min(max(x1, 0.0), iw)
        y0, y1 = min(max(y0, 0.0), ih), min(max(y1, 0.0), ih)
        if x1 - x0 >= 1.0 and y1 - y0 >= 1.0:
            return (x0, y0, x1, y1)
    log.warning("invalid crop box %s for %sx%s image; using centred crop", box, iw, ih)
    return centered_box(iw, ih, out_size[0] / out_size[1]).as_tuple()


def render(
    lt: LabelledTemplate,
    items: dict[int, tuple[str, CropBox]],
    scale: float = 1.0,
    base: Image.Image | None = None,
    getter: ImageGetter = _full,
    only: set[int] | None = None,
    errors: list[str] | None = None,
) -> Image.Image:
    """Paste each cropped image into its placeholder (inside its padding).

    `base` may be a pre-scaled template; `getter` may return reduced images (crop boxes
    stay in original-image pixels and are scaled by the returned per-axis factors).
    A placeholder whose image cannot be read is skipped and described in `errors`.
    """
    if base is None:
        base = Image.open(lt.template_path).convert("RGBA")
        if scale != 1.0:
            base = base.resize((max(1, round(lt.size[0] * scale)), max(1, round(lt.size[1] * scale))), Image.LANCZOS)
    else:
        base = base.copy()
    for ph in lt.placeholders:
        if ph.id not in items or (only is not None and ph.id not in only):
            continue
        path, box = items[ph.id]
        try:
            img, f = getter(path)
        except Exception as e:  # noqa: BLE001
            msg = f"#{ph.id}: cannot read {path}: {e}"
            log.warning(msg)
            if errors is not None:
                errors.append(msg)
            continue
        ix, iy, iw, ih = ph.inset
        x0, y0 = round(ix * scale), round(iy * scale)
        x1, y1 = round((ix + iw) * scale), round((iy + ih) * scale)
        size = (max(1, x1 - x0), max(1, y1 - y0))
        src = safe_source_box(box, img, f, size)
        try:
            piece = img.resize(size, Image.LANCZOS, box=src)
        except ValueError:  # last resort: never abort the whole render over one crop
            log.exception("resize failed for #%s", ph.id)
            piece = img.resize(size, Image.LANCZOS, box=centered_box(*img.size, size[0] / size[1]).as_tuple())
        base.paste(piece, (x0, y0))
    return base
