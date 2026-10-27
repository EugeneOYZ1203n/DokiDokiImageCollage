"""User settings."""
from __future__ import annotations

from dataclasses import dataclass, fields

INSTAGRAM_MODES = ("ask", "resize", "never")
MAX_RECENT_LIMIT = 50


@dataclass
class Settings:
    output_dir: str = ""  # "" = <data dir>/output
    max_recent_folders: int = 10
    crop_tolerance: float = 0.10
    remember_last_save_dir: bool = True
    last_save_dir: str = ""
    instagram_size_mode: str = "ask"  # ask | resize | never
    default_padding: int = 0
    remember_window: bool = True
    window_geometry: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        """Tolerant load: unknown keys ignored, wrong types fall back to the default."""
        s = cls()
        for f in fields(cls):
            if f.name not in d:
                continue
            default = getattr(s, f.name)
            v = d[f.name]
            try:
                if isinstance(default, bool):
                    if not isinstance(v, bool):
                        continue
                elif isinstance(default, int):
                    v = int(v)
                elif isinstance(default, float):
                    v = float(v)
                elif isinstance(default, str):
                    v = str(v)
            except (TypeError, ValueError):
                continue
            setattr(s, f.name, v)
        s.max_recent_folders = max(1, min(MAX_RECENT_LIMIT, s.max_recent_folders))
        s.crop_tolerance = max(0.0, min(1.0, s.crop_tolerance))
        s.default_padding = max(0, s.default_padding)
        if s.instagram_size_mode not in INSTAGRAM_MODES:
            s.instagram_size_mode = "ask"
        return s
