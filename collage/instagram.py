"""Instagram post size checks."""
from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image

PRESETS: dict[str, tuple[int, int]] = {
    "Square 1:1": (1080, 1080),
    "Portrait 4:5": (1080, 1350),
    "Landscape 1.91:1": (1080, 566),
    "Story/Reel 9:16": (1080, 1920),
}
MIN_FEED_AR = 4 / 5
MAX_FEED_AR = 1.91
AR_TOLERANCE = 0.02


@dataclass
class SizeReport:
    ok: bool
    warnings: list[str]
    nearest: str
    nearest_size: tuple[int, int]


def nearest_preset(w: int, h: int) -> tuple[str, tuple[int, int]]:
    import math

    ar = w / h
    name = min(PRESETS, key=lambda n: abs(math.log(ar / (PRESETS[n][0] / PRESETS[n][1]))))
    return name, PRESETS[name]


def check_size(w: int, h: int) -> SizeReport:
    name, (pw, ph) = nearest_preset(w, h)
    warnings: list[str] = []
    if (w, h) in PRESETS.values():
        return SizeReport(True, [], name, (pw, ph))
    ar = w / h
    if abs(ar / (pw / ph) - 1) > AR_TOLERANCE:
        warnings.append(
            f"Aspect ratio {ar:.3f} is not a standard Instagram ratio (closest: {name})."
        )
    if h > w and ar < 9 / 16 - 0.01 or ar > MAX_FEED_AR + 0.01:
        warnings.append("Aspect ratio is outside Instagram's supported range and will be cropped.")
    if w < 1080:
        warnings.append(f"Width {w}px is below 1080px; Instagram will upscale it (blurry).")
    elif w > 1080:
        warnings.append(f"Width {w}px is above 1080px; Instagram will downscale it.")
    if not warnings:
        warnings.append(f"Size {w}x{h} is not a standard preset (closest: {name} {pw}x{ph}).")
    return SizeReport(False, warnings, name, (pw, ph))


def check_file_size(path: str, limit_mb: float = 8.0) -> str | None:
    try:
        mb = os.path.getsize(path) / 1e6
    except OSError:
        return None
    if mb > limit_mb:
        return f"Output is {mb:.1f} MB; Instagram may recompress files over ~{limit_mb:.0f} MB."
    return None


def resize_template_image(src: str, size: tuple[int, int], dest: str) -> None:
    Image.open(src).convert("RGBA").resize(size, Image.LANCZOS).save(dest)
