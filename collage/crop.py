"""Crop boxes (image-pixel coordinates, fixed aspect)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .saliency import saliency_map

MIN_BOX = 8.0


@dataclass
class CropBox:
    x: float
    y: float
    w: float
    h: float

    def scaled(self, f: float) -> "CropBox":
        return CropBox(self.x * f, self.y * f, self.w * f, self.h * f)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def is_finite(self) -> bool:
        return all(math.isfinite(v) for v in (self.x, self.y, self.w, self.h)) and self.w > 0 and self.h > 0


def max_box(iw: float, ih: float, ar: float) -> tuple[float, float]:
    if iw / ih > ar:
        return ih * ar, ih
    return iw, iw / ar


def centered_box(iw: float, ih: float, ar: float) -> CropBox:
    w, h = max_box(iw, ih, ar)
    return CropBox((iw - w) / 2, (ih - h) / 2, w, h)


def fits_aspect(iw: float, ih: float, ar: float, tol: float) -> bool:
    return abs((iw / ih) / ar - 1.0) <= tol


def fit_box(box: CropBox, iw: float, ih: float, ar: float, min_w: float = MIN_BOX) -> CropBox:
    """Guard: return a box with exactly aspect `ar` that lies inside the iw x ih image.

    Bad input (NaN, non-positive size, outside the image) degrades to the nearest valid box
    (centred when nothing usable is left). Works for images smaller than `min_w`.
    """
    if not (math.isfinite(ar) and ar > 0 and iw > 0 and ih > 0):
        raise ValueError(f"cannot fit a box in a {iw}x{ih} image with aspect {ar}")
    if not box.is_finite():
        return centered_box(iw, ih, ar)
    mw, _ = max_box(iw, ih, ar)
    w = min(max(box.w, min(min_w, mw)), mw)
    h = w / ar
    x = min(max(box.x, 0.0), max(0.0, iw - w))
    y = min(max(box.y, 0.0), max(0.0, ih - h))
    return CropBox(x, y, w, h)


def clamp_box(box: CropBox, iw: float, ih: float, min_w: float = MIN_BOX) -> CropBox:
    """Clamp keeping the box's own aspect."""
    if not box.is_finite():
        raise ValueError("invalid crop box")
    return fit_box(box, iw, ih, box.w / box.h, min_w)


def pan(box: CropBox, dx: float, dy: float, iw: float, ih: float) -> CropBox:
    return clamp_box(CropBox(box.x + dx, box.y + dy, box.w, box.h), iw, ih)


def zoom(box: CropBox, factor: float, iw: float, ih: float, anchor=None, min_w: float = MIN_BOX) -> CropBox:
    """factor > 1 zooms in (smaller box). `anchor` = image point kept at the same box fraction."""
    if not (math.isfinite(factor) and factor > 0):
        return box
    ar = box.w / box.h
    ax, ay = anchor if anchor else (box.x + box.w / 2, box.y + box.h / 2)
    fx = (ax - box.x) / box.w
    fy = (ay - box.y) / box.h
    mw, _ = max_box(iw, ih, ar)
    w = min(max(box.w / factor, min(min_w, mw)), mw)
    h = w / ar
    return fit_box(CropBox(ax - fx * w, ay - fy * h, w, h), iw, ih, ar, min_w)


def resize_corner(box: CropBox, corner: str, px: float, py: float, iw: float, ih: float, min_w: float = MIN_BOX) -> CropBox:
    """Drag a corner with the opposite corner fixed, aspect locked, inside the image."""
    ar = box.w / box.h
    sx = -1 if "w" in corner else 1
    sy = -1 if "n" in corner else 1
    ax = box.x + box.w if sx < 0 else box.x
    ay = box.y + box.h if sy < 0 else box.y
    want = max((px - ax) * sx, (py - ay) * sy * ar, 0.0)
    room_x = ax if sx < 0 else iw - ax
    room_y = ay if sy < 0 else ih - ay
    mw, _ = max_box(iw, ih, ar)
    w = min(want, room_x, room_y * ar)
    w = max(w, min(min_w, mw, room_x, room_y * ar))
    h = w / ar
    return fit_box(CropBox(ax if sx > 0 else ax - w, ay if sy > 0 else ay - h, w, h), iw, ih, ar, min_w)


def best_crop(sal: np.ndarray, iw: float, ih: float, ar: float) -> CropBox:
    """Crop of aspect `ar` that keeps the most saliency, preferring larger boxes.

    Searched on the saliency map, then rebuilt in image pixels with the exact aspect.
    """
    sh, sw = sal.shape
    fx, fy = iw / sw, ih / sh
    # box in map coords whose *image-space* aspect is `ar`
    mw_img, mh_img = max_box(iw, ih, ar)
    mw, mh = mw_img / fx, mh_img / fy
    integral = cv2.integral(sal.astype(np.float64))
    total = float(integral[-1, -1]) or 1.0
    best = None
    for s in (1.0, 0.85, 0.7, 0.55):
        bw, bh = mw * s, mh * s
        for x in np.linspace(0, max(0.0, sw - bw), 17 if sw - bw > 0.5 else 1):
            for y in np.linspace(0, max(0.0, sh - bh), 17 if sh - bh > 0.5 else 1):
                x0, y0 = int(round(x)), int(round(y))
                x1 = min(sw, max(x0 + 1, int(round(x + bw))))
                y1 = min(sh, max(y0 + 1, int(round(y + bh))))
                inside = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
                score = inside / total + 0.4 * s
                if best is None or score > best[0]:
                    best = (score, x, y, s)
    _, x, y, s = best
    return fit_box(CropBox(x * fx, y * fy, mw_img * s, mh_img * s), iw, ih, ar)


def auto_crop(img: Image.Image, ar: float, tolerance: float) -> CropBox:
    """Centre fit if aspect is within `tolerance`, otherwise saliency-based crop."""
    iw, ih = img.size
    if fits_aspect(iw, ih, ar, tolerance):
        return centered_box(iw, ih, ar)
    return best_crop(saliency_map(img), iw, ih, ar)
