"""Load per-tag image pools with cached dominant colours."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageOps

from .colors import dominant_lab
from .imageio import list_images


def _dominant(path: str):
    try:
        img = Image.open(path)
        if img.format == "JPEG":
            img.draft("RGB", (160, 160))
        img = ImageOps.exif_transpose(img).convert("RGB")
        return dominant_lab(img)
    except Exception:  # noqa: BLE001 - unreadable file: skip it
        return None


def load_pools(
    folders: dict[str, str],
    tags: list[str],
    cache: dict,
    report=lambda frac, text="": None,
) -> dict[str, tuple[list[str], np.ndarray]]:
    """tag -> (paths, Lab colours). Unreadable images are dropped."""
    listing = {t: list_images(folders[t]) for t in tags if t in folders}
    todo = [p for paths in listing.values() for p in paths if p not in cache]
    done = 0
    if todo:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for p, lab in zip(todo, ex.map(_dominant, todo)):
                cache[p] = lab
                done += 1
                report(done / len(todo), f"Analysing colours {done}/{len(todo)}")
    pools = {}
    for t, paths in listing.items():
        ok = [p for p in paths if cache.get(p) is not None]
        pools[t] = (ok, np.array([cache[p] for p in ok]).reshape(-1, 3))
    return pools
