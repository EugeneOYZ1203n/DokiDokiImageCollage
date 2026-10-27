"""Labelled template data model + JSON IO."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field


@dataclass
class Placeholder:
    id: int
    x: float
    y: float
    w: float
    h: float
    tag: str = ""
    padding: int = 0

    @property
    def inset(self) -> tuple[float, float, float, float]:
        """Rect the image actually fills: the placeholder shrunk by `padding` on every side."""
        p = max(0.0, min(float(self.padding), (min(self.w, self.h) - 1) / 2))
        return (self.x + p, self.y + p, self.w - 2 * p, self.h - 2 * p)

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)

    @rect.setter
    def rect(self, r) -> None:
        self.x, self.y, self.w, self.h = r

    @property
    def aspect(self) -> float:
        return self.w / self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": round(self.x),
            "y": round(self.y),
            "w": round(self.w),
            "h": round(self.h),
            "tag": self.tag,
            "padding": int(self.padding),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Placeholder":
        return cls(int(d["id"]), d["x"], d["y"], d["w"], d["h"], d.get("tag", ""), int(d.get("padding", 0)))


@dataclass
class LabelledTemplate:
    template_path: str
    size: tuple[int, int]
    placeholders: list[Placeholder] = field(default_factory=list)

    def next_id(self) -> int:
        return max((p.id for p in self.placeholders), default=0) + 1

    def get(self, pid: int) -> Placeholder | None:
        return next((p for p in self.placeholders if p.id == pid), None)

    def by_tag(self, tag: str) -> list[Placeholder]:
        return sorted((p for p in self.placeholders if p.tag == tag), key=lambda p: p.id)

    def tags_used(self) -> list[str]:
        seen: list[str] = []
        for p in sorted(self.placeholders, key=lambda p: p.id):
            if p.tag and p.tag not in seen:
                seen.append(p.tag)
        return seen

    def to_dict(self) -> dict:
        return {
            "template": self.template_path,
            "size": list(self.size),
            "placeholders": [p.to_dict() for p in self.placeholders],
        }

    def scaled(self, new_size: tuple[int, int], new_path: str | None = None) -> "LabelledTemplate":
        sx = new_size[0] / self.size[0]
        sy = new_size[1] / self.size[1]
        phs = [
            Placeholder(p.id, p.x * sx, p.y * sy, p.w * sx, p.h * sy, p.tag, round(p.padding * (sx + sy) / 2))
            for p in self.placeholders
        ]
        return LabelledTemplate(new_path or self.template_path, tuple(new_size), phs)


def clamp_placeholder(p: Placeholder, size: tuple[int, int]) -> Placeholder | None:
    """Pull a placeholder inside the canvas; None if nothing usable is left."""
    W, H = size
    x0, y0 = max(0.0, p.x), max(0.0, p.y)
    x1, y1 = min(float(W), p.x + p.w), min(float(H), p.y + p.h)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    p.rect = (x0, y0, x1 - x0, y1 - y0)
    p.padding = max(0, min(int(p.padding), int((min(p.w, p.h) - 1) // 2)))
    return p


def save_labelled(lt: LabelledTemplate, path: str) -> None:
    """Save next to its image: a template image living elsewhere is copied beside the JSON,
    and the JSON stores just the file name so the pair can be moved together."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    src = lt.template_path
    if os.path.isabs(src) and os.path.isfile(src) and not _same_dir(os.path.dirname(src), directory):
        stem, ext = os.path.splitext(os.path.basename(src))
        dest = unique_path(directory, stem, ext)
        shutil.copy2(src, dest)
        lt.template_path = os.path.abspath(dest)
    data = lt.to_dict()
    if os.path.isabs(lt.template_path) and _same_dir(os.path.dirname(lt.template_path), directory):
        data["template"] = os.path.basename(lt.template_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _same_dir(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def load_labelled(path: str) -> LabelledTemplate:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    tpl = d["template"]
    here = os.path.dirname(os.path.abspath(path))
    if not os.path.isabs(tpl):
        tpl = os.path.join(here, tpl)
    elif not os.path.exists(tpl):
        # absolute path from another machine/location: fall back to a copy beside the JSON
        alt = os.path.join(here, os.path.basename(tpl.replace("\\", "/")))
        if os.path.exists(alt):
            tpl = alt
    try:
        size = (int(d["size"][0]), int(d["size"][1]))
        phs = [Placeholder.from_dict(p) for p in d.get("placeholders", [])]
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise ValueError(f"{path} is not a valid labelled template ({type(e).__name__}: {e})") from e
    if size[0] < 1 or size[1] < 1:
        raise ValueError(f"{path}: invalid template size {size}")
    return LabelledTemplate(tpl, size, [q for q in (clamp_placeholder(p, size) for p in phs) if q])


def list_labelled(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, n) for n in os.listdir(directory) if n.lower().endswith(".json")
    )


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip().strip(".")
    return name or "template"


def unique_path(directory: str, name: str, ext: str = ".json") -> str:
    name = safe_name(name)
    path = os.path.join(directory, name + ext)
    i = 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{name}_{i}{ext}")
        i += 1
    return path


def rename_labelled(path: str, new_name: str) -> str:
    """Rename a saved labelled template file. Returns new path."""
    directory = os.path.dirname(os.path.abspath(path))
    new_path = os.path.join(directory, safe_name(new_name) + ".json")
    if os.path.abspath(new_path) == os.path.abspath(path):
        return path
    if os.path.exists(new_path):
        raise FileExistsError(new_path)
    os.replace(path, new_path)
    return new_path
