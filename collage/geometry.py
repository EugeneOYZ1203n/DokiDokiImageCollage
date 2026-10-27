"""Placeholder rectangle editing: move/resize with snapping and aspect lock."""
from __future__ import annotations

Rect = tuple[float, float, float, float]
Size = tuple[float, float]

HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


def _targets(others: list[Rect], size: Size) -> tuple[list[float], list[float]]:
    W, H = size
    xs = [0.0, W / 2, W]
    ys = [0.0, H / 2, H]
    for x, y, w, h in others:
        xs += [x, x + w / 2, x + w]
        ys += [y, y + h / 2, y + h]
    return xs, ys


def snap_value(v: float, targets: list[float], thr: float) -> float:
    best = v
    best_d = thr + 1e-9
    for t in targets:
        d = abs(t - v)
        if d < best_d:
            best, best_d = t, d
    return best


def _best_delta(edges: list[float], targets: list[float], thr: float) -> float:
    best = 0.0
    best_d = thr + 1e-9
    for e in edges:
        for t in targets:
            d = abs(t - e)
            if d < best_d:
                best, best_d = t - e, d
    return best


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def snap_move(rect: Rect, others: list[Rect], size: Size, thr: float) -> Rect:
    """Snap left/centre/right and top/middle/bottom of a moved rect to neighbours."""
    x, y, w, h = rect
    xs, ys = _targets(others, size)
    x += _best_delta([x, x + w / 2, x + w], xs, thr)
    y += _best_delta([y, y + h / 2, y + h], ys, thr)
    x = _clamp(x, 0, max(0, size[0] - w))
    y = _clamp(y, 0, max(0, size[1] - h))
    return (x, y, w, h)


def hit_test(rect: Rect, px: float, py: float, tol: float) -> str | None:
    """Return handle name, 'move' if inside, else None."""
    x, y, w, h = rect
    cx, cy = x + w / 2, y + h / 2
    pts = {
        "nw": (x, y), "n": (cx, y), "ne": (x + w, y), "e": (x + w, cy),
        "se": (x + w, y + h), "s": (cx, y + h), "sw": (x, y + h), "w": (x, cy),
    }
    for name in ("nw", "ne", "se", "sw", "n", "s", "e", "w"):
        hx, hy = pts[name]
        if abs(px - hx) <= tol and abs(py - hy) <= tol:
            return name
    if x <= px <= x + w and y <= py <= y + h:
        return "move"
    return None


def resize_rect(
    rect: Rect,
    handle: str,
    px: float,
    py: float,
    others: list[Rect],
    size: Size,
    lock: bool,
    thr: float,
    min_size: float = 8,
) -> Rect:
    """Drag `handle` to pointer (px, py). Snaps edges to neighbours; snaps w/h to
    neighbours' dimensions; keeps aspect when `lock`."""
    x, y, w, h = rect
    W, H = size
    xs, ys = _targets(others, size)
    l, t, r, b = x, y, x + w, y + h
    px = _clamp(px, 0, W)
    py = _clamp(py, 0, H)

    snapped_x = snapped_y = False
    if "w" in handle:
        nl = snap_value(px, xs, thr)
        snapped_x = nl != px
        l = nl
    if "e" in handle:
        nr = snap_value(px, xs, thr)
        snapped_x = nr != px
        r = nr
    if "n" in handle:
        nt = snap_value(py, ys, thr)
        snapped_y = nt != py
        t = nt
    if "s" in handle:
        nb = snap_value(py, ys, thr)
        snapped_y = nb != py
        b = nb

    if "w" in handle:
        l = min(l, r - min_size)
    if "e" in handle:
        r = max(r, l + min_size)
    if "n" in handle:
        t = min(t, b - min_size)
    if "s" in handle:
        b = max(b, t + min_size)

    if lock and w > 0 and h > 0:
        return _resize_locked(rect, handle, l, t, r, b, size, min_size)

    # snap dimensions to neighbours (only if the edge itself didn't snap)
    if ("w" in handle or "e" in handle) and not snapped_x:
        nw = r - l
        for _, _, ow, _ in others:
            if abs(nw - ow) <= thr:
                if "e" in handle:
                    r = min(W, l + ow)
                else:
                    l = max(0, r - ow)
                break
    if ("n" in handle or "s" in handle) and not snapped_y:
        nh = b - t
        for _, _, _, oh in others:
            if abs(nh - oh) <= thr:
                if "s" in handle:
                    b = min(H, t + oh)
                else:
                    t = max(0, b - oh)
                break
    return (l, t, r - l, b - t)


def _resize_locked(rect: Rect, handle: str, l, t, r, b, size: Size, min_size: float) -> Rect:
    x, y, w, h = rect
    W, H = size
    ar = w / h
    nw, nh = r - l, b - t
    if len(handle) == 2:
        if nw / w >= nh / h:
            nh = nw / ar
        else:
            nw = nh * ar
        ax = x if "e" in handle else x + w
        ay = y if "s" in handle else y + h
        maxw = (W - ax) if "e" in handle else ax
        maxh = (H - ay) if "s" in handle else ay
        s = min(1.0, maxw / nw, maxh / nh)
        nw, nh = nw * s, nh * s
        if nw < min_size:
            nw, nh = min_size, min_size / ar
        nl = ax if "e" in handle else ax - nw
        nt = ay if "s" in handle else ay - nh
        return (nl, nt, nw, nh)
    if handle in ("e", "w"):
        nh = nw / ar
        cy = y + h / 2
        maxh = 2 * min(cy, H - cy)
        maxw = (W - x) if handle == "e" else (x + w)
        s = min(1.0, maxw / nw, maxh / nh)
        nw, nh = nw * s, nh * s
        if nw < min_size:
            nw, nh = min_size, min_size / ar
        nl = x if handle == "e" else x + w - nw
        return (nl, cy - nh / 2, nw, nh)
    # n / s
    nw = nh * ar
    cx = x + w / 2
    maxw = 2 * min(cx, W - cx)
    maxh = (H - y) if handle == "s" else (y + h)
    s = min(1.0, maxh / nh, maxw / nw)
    nw, nh = nw * s, nh * s
    if nh < min_size:
        nh, nw = min_size, min_size * ar
    nt = y if handle == "s" else y + h - nh
    return (cx - nw / 2, nt, nw, nh)


def set_field(rect: Rect, field: str, value: float, lock: bool, size: Size, min_size: float = 1) -> Rect:
    """Numeric edit of x / y / w / h. With `lock`, editing w or h keeps the aspect."""
    x, y, w, h = rect
    W, H = size
    ar = w / h if h else 1.0
    if field == "x":
        x = _clamp(value, 0, W - w)
    elif field == "y":
        y = _clamp(value, 0, H - h)
    elif field == "w":
        w = _clamp(value, min_size, W - x)
        if lock:
            h = w / ar
            if y + h > H:
                h = H - y
                w = h * ar

    elif field == "h":
        h = _clamp(value, min_size, H - y)
        if lock:
            w = h * ar
            if x + w > W:
                w = W - x
                h = w / ar
    else:
        raise ValueError(field)
    return (x, y, w, h)


# ---------- multi-select helpers
def bounds(rects: list[Rect]) -> Rect:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def snap_move_group(rects: list[Rect], dx: float, dy: float, others: list[Rect], size: Size, thr: float) -> tuple[float, float]:
    """Move a group by (dx, dy); snap the group's bounds to `others`. Returns the final (dx, dy)."""
    bx, by, bw, bh = bounds(rects)
    sx, sy, _, _ = snap_move((bx + dx, by + dy, bw, bh), others, size, thr)
    return (sx - bx, sy - by)


ALIGNS = ("left", "center", "right", "top", "middle", "bottom")


def align(rects: list[Rect], how: str, ref: Rect | None = None) -> list[Rect]:
    """PowerPoint-style align. `ref` defaults to the selection bounds."""
    rx, ry, rw, rh = ref if ref is not None else bounds(rects)
    out = []
    for x, y, w, h in rects:
        if how == "left":
            x = rx
        elif how == "center":
            x = rx + (rw - w) / 2
        elif how == "right":
            x = rx + rw - w
        elif how == "top":
            y = ry
        elif how == "middle":
            y = ry + (rh - h) / 2
        elif how == "bottom":
            y = ry + rh - h
        else:
            raise ValueError(how)
        out.append((x, y, w, h))
    return out


def distribute(rects: list[Rect], axis: str) -> list[Rect]:
    """Equal gaps between neighbouring edges along `axis` ('h' or 'v'); outermost stay put."""
    n = len(rects)
    if n < 3:
        return list(rects)
    i0, s0 = (0, 2) if axis == "h" else (1, 3)
    order = sorted(range(n), key=lambda i: rects[i][i0])
    start = min(r[i0] for r in rects)
    end = max(r[i0] + r[s0] for r in rects)
    gap = (end - start - sum(r[s0] for r in rects)) / (n - 1)
    out = list(rects)
    pos = start
    for i in order:
        r = list(rects[i])
        r[i0] = pos
        out[i] = tuple(r)
        pos += r[s0] + gap
    return out


def split_grid(rect: Rect, rows: int, cols: int, gap: int = 0) -> list[Rect]:
    """Split a rect into rows x cols cells (row-major). Integer cells tile the rect exactly;
    leftover pixels go to the first cells."""
    if rows < 1 or cols < 1:
        raise ValueError("rows and cols must be >= 1")
    if gap < 0:
        raise ValueError("gap must be >= 0")
    x, y, w, h = (round(v) for v in rect)
    aw = w - gap * (cols - 1)
    ah = h - gap * (rows - 1)
    if aw < cols or ah < rows:
        raise ValueError("rectangle too small for that grid")
    cells: list[Rect] = []
    cy = y
    for r in range(rows):
        ch = ah // rows + (1 if r < ah % rows else 0)
        cx = x
        for c in range(cols):
            cw = aw // cols + (1 if c < aw % cols else 0)
            cells.append((float(cx), float(cy), float(cw), float(ch)))
            cx += cw + gap
        cy += ch + gap
    return cells
