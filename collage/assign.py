"""Auto image selection: random, gradient, or colour scheme."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import colors
from .models import LabelledTemplate, Placeholder


class NoFit(Exception):
    """Pool cannot satisfy constraints."""

    def __init__(self, message: str, fit: int = 0, needed: int = 0):
        super().__init__(message)
        self.fit = fit
        self.needed = needed


class PoolTooSmall(Exception):
    pass


@dataclass
class AutoParams:
    mode: str = "random"  # random | gradient | scheme
    gradient_kind: str = "linear"  # linear | radial
    angle: float = 0.0  # degrees, linear: 0 = left->right, 90 = top->bottom
    center: tuple[float, float] = (0.5, 0.5)  # radial, normalised
    start: tuple[int, int, int] = (255, 0, 0)
    end: tuple[int, int, int] = (0, 0, 255)
    max_delta: float = 35.0  # Lab dE counted as "fits" for gradient
    scheme: str = colors.ANY_SCHEME
    bases: list = field(default_factory=list)
    tolerance: float = 30.0  # hue degrees
    seed: int | None = None
    strict: bool = True  # raise NoFit when constraints cannot be met


def gradient_t(ph: Placeholder, size, kind: str, angle: float, center) -> float:
    W, H = size
    cx, cy = ph.center
    if kind == "radial":
        ox, oy = center[0] * W, center[1] * H
        far = max(math.hypot(ox - qx, oy - qy) for qx in (0, W) for qy in (0, H)) or 1.0
        return min(1.0, math.hypot(cx - ox, cy - oy) / far)
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    extent = abs(W * dx) + abs(H * dy) or 1.0
    t = ((cx - W / 2) * dx + (cy - H / 2) * dy) / extent + 0.5
    return min(1.0, max(0.0, t))


def gradient_targets(phs: list[Placeholder], size, params: AutoParams) -> np.ndarray:
    s = colors.rgb_to_lab(params.start).astype(np.float64)
    e = colors.rgb_to_lab(params.end).astype(np.float64)
    out = []
    for ph in phs:
        t = gradient_t(ph, size, params.gradient_kind, params.angle, params.center)
        out.append(s + (e - s) * t)
    return np.array(out)


def assign_gradient(labs, targets, max_delta: float, strict: bool) -> list[int]:
    """Index into pool for each target (Hungarian, minimising total dE)."""
    labs = np.asarray(labs, dtype=np.float64).reshape(-1, 3)
    cost = np.linalg.norm(labs[:, None, :] - targets[None, :, :], axis=2)
    rows, cols = linear_sum_assignment(cost)
    result = [0] * len(targets)
    bad = 0
    for r, c in zip(rows, cols):
        result[c] = int(r)
        if cost[r, c] > max_delta:
            bad += 1
    if strict and bad:
        raise NoFit(
            f"{bad} of {len(targets)} placeholders have no image within dE {max_delta:.0f} "
            "of their gradient colour.",
            fit=len(targets) - bad,
            needed=len(targets),
        )
    return result


def resolve_scheme(labs, n: int, params: AutoParams) -> tuple[str, list]:
    if params.scheme == colors.ANY_SCHEME:
        scheme, base, _ = colors.best_scheme_any(labs, n)
        return scheme, [base]
    if not params.bases:
        raise NoFit("No base colour chosen for the colour scheme.", 0, n)
    return params.scheme, list(params.bases)


def assign_scheme(labs, n: int, params: AutoParams, rng: random.Random) -> list[int]:
    scheme, bases = resolve_scheme(labs, n, params)
    errs = colors.scheme_errors(labs, scheme, bases)
    order = np.argsort(errs, kind="stable")
    eligible = int((errs <= params.tolerance).sum())
    if params.strict and params.scheme != colors.ANY_SCHEME and eligible < n:
        raise NoFit(
            f"Only {eligible} image(s) match the {scheme} scheme within "
            f"{params.tolerance:.0f}° (need {n}).",
            fit=eligible,
            needed=n,
        )
    chosen = [int(i) for i in order[:n]]
    rng.shuffle(chosen)
    return chosen


def auto_assign(
    lt: LabelledTemplate,
    pools: dict[str, tuple[list[str], np.ndarray]],
    params: AutoParams,
) -> dict[int, str]:
    """pools: tag -> (paths, labs). Returns placeholder id -> image path. No reuse."""
    rng = random.Random(params.seed)
    out: dict[int, str] = {}
    problems: list[str] = []
    fits = needed = 0
    for tag in lt.tags_used():
        phs = lt.by_tag(tag)
        paths, labs = pools.get(tag, ([], np.zeros((0, 3))))
        if len(paths) < len(phs):
            raise PoolTooSmall(
                f"Tag {tag!r}: {len(phs)} placeholder(s) but only {len(paths)} image(s)."
            )
        try:
            if params.mode == "gradient":
                idx = assign_gradient(labs, gradient_targets(phs, lt.size, params), params.max_delta, params.strict)
            elif params.mode == "scheme":
                idx = assign_scheme(labs, len(phs), params, rng)
            else:
                idx = rng.sample(range(len(paths)), len(phs))
        except NoFit as e:
            problems.append(f"[{tag}] {e}")
            fits += e.fit
            needed += e.needed
            continue
        for ph, i in zip(phs, idx):
            out[ph.id] = paths[i]
    if problems:
        raise NoFit("\n".join(problems), fits, needed)
    return out


def suggest(lt: LabelledTemplate, pools, params: AutoParams) -> AutoParams:
    """Return a copy of params with suggested colours for the pool."""
    import copy

    p = copy.deepcopy(params)
    all_labs = [l for _, labs in pools.values() for l in np.asarray(labs).reshape(-1, 3)]
    if not all_labs:
        return p
    if params.mode == "gradient":
        p.start, p.end = colors.suggest_gradient(all_labs)
    elif params.mode == "scheme":
        n = len(lt.placeholders)
        scheme = params.scheme
        if scheme == colors.ANY_SCHEME:
            scheme, base, _ = colors.best_scheme_any(all_labs, n)
            p.scheme = scheme
            p.bases = [base]
        else:
            p.bases = [colors.suggest_scheme_base(all_labs, scheme, n)]
    return p
