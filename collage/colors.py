"""Colour analysis: Lab conversion, dominant colour, hue schemes, suggestions."""
from __future__ import annotations

import colorsys

import cv2
import numpy as np
from PIL import Image

SCHEMES: dict[str, tuple[float, ...]] = {
    "monotone": (0,),
    "analogous": (-30, 0, 30),
    "complementary": (0, 180),
    "split-complementary": (0, 150, 210),
    "triadic": (0, 120, 240),
    "tetradic": (0, 90, 180, 270),
}
ANY_SCHEME = "any"
MIN_SATURATION = 0.12  # below this an image is treated as neutral (no hue)


def rgb_to_lab(rgb) -> np.ndarray:
    a = np.asarray(rgb, dtype=np.float32)
    flat = a.reshape(-1, 1, 3) / 255.0
    return cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).reshape(a.shape)


def lab_to_rgb(lab) -> np.ndarray:
    a = np.asarray(lab, dtype=np.float32)
    flat = a.reshape(-1, 1, 3)
    rgb = cv2.cvtColor(flat, cv2.COLOR_LAB2RGB).reshape(a.shape)
    return np.clip(rgb * 255.0, 0, 255)


def dominant_lab(img: Image.Image, k: int = 3) -> np.ndarray:
    """Centre (Lab) of the largest k-means cluster of a downscaled image."""
    small = img.convert("RGB")
    small.thumbnail((64, 64))
    lab = rgb_to_lab(np.asarray(small)).reshape(-1, 3).astype(np.float32)
    if k <= 1 or np.ptp(lab, axis=0).max() < 1.0 or len(lab) < k:
        return lab.mean(axis=0)
    cv2.setRNGSeed(0)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(lab, k, None, crit, 1, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    return centers[int(np.argmax(counts))]


def lab_hue_sat(lab) -> tuple[float, float]:
    r, g, b = lab_to_rgb(lab) / 255.0
    h, s, _ = colorsys.rgb_to_hsv(float(r), float(g), float(b))
    return h * 360.0, s


def rgb_hue(rgb) -> float:
    r, g, b = (float(c) / 255.0 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360.0


def hue_to_rgb(hue: float, s: float = 0.75, v: float = 0.85) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, s, v)
    return (round(r * 255), round(g * 255), round(b * 255))


def _hue_sat_arrays(labs) -> tuple[np.ndarray, np.ndarray]:
    labs = np.asarray(labs, dtype=np.float32).reshape(-1, 3)
    rgb = lab_to_rgb(labs) / 255.0
    hs = np.array([colorsys.rgb_to_hsv(*map(float, c)) for c in rgb])
    return hs[:, 0] * 360.0, hs[:, 1]


def _hue_errors(hues: np.ndarray, sats: np.ndarray, targets: np.ndarray) -> np.ndarray:
    d = np.abs((hues[:, None] - targets[None, :] + 180.0) % 360.0 - 180.0).min(axis=1)
    d = d.astype(np.float64)
    d[sats < MIN_SATURATION] = 180.0
    return d


def target_hues(scheme: str, base_hues: list[float]) -> np.ndarray:
    offs = SCHEMES[scheme]
    return np.array([(b + o) % 360.0 for b in base_hues for o in offs])


def scheme_errors(labs, scheme: str, bases_rgb: list) -> np.ndarray:
    """Hue error (degrees, 0..180) of each image colour to the scheme around the bases."""
    hues, sats = _hue_sat_arrays(labs)
    return _hue_errors(hues, sats, target_hues(scheme, [rgb_hue(b) for b in bases_rgb]))


def _score(errs: np.ndarray, n: int, scheme: str) -> float:
    best = np.sort(errs)[:n]
    return float(best.mean()) + 5.0 * (len(SCHEMES[scheme]) - 1)


def best_scheme_any(labs, n: int, step: float = 10.0) -> tuple[str, tuple[int, int, int], float]:
    """Pick the scheme + base hue whose top-n images fit best. Wider schemes pay a penalty."""
    hues, sats = _hue_sat_arrays(labs)
    n = min(n, len(hues))
    best: tuple[float, str, float] | None = None
    for scheme in SCHEMES:
        for base in np.arange(0.0, 360.0, step):
            errs = _hue_errors(hues, sats, target_hues(scheme, [base]))
            sc = _score(errs, n, scheme)
            if best is None or sc < best[0]:
                best = (sc, scheme, float(base))
    assert best is not None
    return best[1], hue_to_rgb(best[2]), best[0]


def suggest_scheme_base(labs, scheme: str, n: int, step: float = 5.0) -> tuple[int, int, int]:
    hues, sats = _hue_sat_arrays(labs)
    n = min(n, len(hues))
    best_base, best_sc = 0.0, float("inf")
    for base in np.arange(0.0, 360.0, step):
        errs = _hue_errors(hues, sats, target_hues(scheme, [base]))
        sc = float(np.sort(errs)[:n].mean())
        if sc < best_sc:
            best_base, best_sc = float(base), sc
    return hue_to_rgb(best_base)


def suggest_gradient(labs, low_pct: float = 5.0, high_pct: float = 95.0) -> tuple[tuple, tuple]:
    """Endpoints along the principal Lab axis of the pool (outliers trimmed)."""
    labs = np.asarray(labs, dtype=np.float64).reshape(-1, 3)
    if len(labs) == 1:
        c = tuple(int(v) for v in lab_to_rgb(labs[0]))
        return c, c
    mean = labs.mean(axis=0)
    _, _, vt = np.linalg.svd(labs - mean, full_matrices=False)
    axis = vt[0]
    proj = (labs - mean) @ axis
    lo, hi = np.percentile(proj, [low_pct, high_pct])
    i_lo = int(np.argmin(np.abs(proj - lo)))
    i_hi = int(np.argmin(np.abs(proj - hi)))
    to_rgb = lambda l: tuple(int(round(v)) for v in lab_to_rgb(l))
    return to_rgb(labs[i_lo]), to_rgb(labs[i_hi])


def delta_e(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))
