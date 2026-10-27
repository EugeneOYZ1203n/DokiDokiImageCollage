"""Per-user local storage: settings, recent image folders, labelled templates, logs.

Lives in %APPDATA%\\DokiDokiCollage so it works the same from source and from a frozen exe
(the exe's CWD and install dir are not writable/stable).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict

from .config import Settings
from .models import list_labelled, load_labelled, save_labelled

APP_NAME = "DokiDokiCollage"
log = logging.getLogger(__name__)


def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    name = APP_NAME if os.environ.get("APPDATA") else "." + APP_NAME.lower()
    return os.path.join(base, name)


def norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class Store:
    def __init__(self, root: str | None = None):
        self.root = root or app_dir()
        self.path = os.path.join(self.root, "settings.json")
        self.settings = Settings()
        self.recent_folders: list[str] = []
        self.legacy_migrated = False
        os.makedirs(self.templates_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        self.load()

    # ---------- locations
    @property
    def templates_dir(self) -> str:
        return os.path.join(self.root, "templates")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.root, "logs")

    @property
    def log_file(self) -> str:
        return os.path.join(self.logs_dir, "collage.log")

    @property
    def default_output_dir(self) -> str:
        return os.path.join(self.root, "output")

    def save_dialog_dir(self) -> str:
        """Where the Save-As dialog starts."""
        s = self.settings
        if s.remember_last_save_dir and s.last_save_dir and os.path.isdir(s.last_save_dir):
            return s.last_save_dir
        return s.output_dir or self.default_output_dir

    def note_saved(self, path: str) -> None:
        if self.settings.remember_last_save_dir:
            self.settings.last_save_dir = os.path.dirname(os.path.abspath(path))
            self.save()

    # ---------- persistence
    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError("root is not an object")
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("settings unreadable (%s); starting fresh", e)
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return
        self.settings = Settings.from_dict(d.get("settings") if isinstance(d.get("settings"), dict) else {})
        rec = d.get("recent_folders")
        self.recent_folders = [p for p in rec if isinstance(p, str)] if isinstance(rec, list) else []
        self.legacy_migrated = bool(d.get("legacy_migrated", False))
        self._trim_recent()

    def save(self) -> None:
        data = {
            "settings": asdict(self.settings),
            "recent_folders": self.recent_folders,
            "legacy_migrated": self.legacy_migrated,
        }
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as e:
            log.error("cannot save settings: %s", e)

    def set_settings(self, s: Settings) -> None:
        self.settings = s
        self._trim_recent()
        self.save()

    # ---------- recent image folders (MRU, capped)
    def _trim_recent(self) -> None:
        seen: set[str] = set()
        out: list[str] = []
        for p in self.recent_folders:
            k = norm(p)
            if k not in seen:
                seen.add(k)
                out.append(p)
        self.recent_folders = out[: self.settings.max_recent_folders]

    def add_recent(self, folder: str) -> None:
        folder = os.path.abspath(folder)
        self.recent_folders = [folder] + [p for p in self.recent_folders if norm(p) != norm(folder)]
        self._trim_recent()
        self.save()

    def remove_recent(self, folder: str) -> None:
        self.recent_folders = [p for p in self.recent_folders if norm(p) != norm(folder)]
        self.save()

    def clear_recent(self) -> None:
        self.recent_folders = []
        self.save()

    # ---------- first-run migration of ./labelled_templates
    def migrate_legacy(self, candidates: list[str]) -> int:
        """Copy old labelled templates (and their images) into storage, once. Returns count copied."""
        if self.legacy_migrated:
            return 0
        n = 0
        seen: set[str] = set()
        for d in candidates:
            if not d or norm(d) in seen or norm(d) == norm(self.templates_dir):
                continue
            seen.add(norm(d))
            for jp in list_labelled(d):
                dest = os.path.join(self.templates_dir, os.path.basename(jp))
                if os.path.exists(dest):
                    continue
                try:
                    lt = load_labelled(jp)
                    save_labelled(lt, dest)  # copies the image beside it, stores its name
                    n += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("skip legacy template %s: %s", jp, e)
        self.legacy_migrated = True
        self.save()
        return n


def legacy_template_dirs() -> list[str]:
    dirs = [os.path.join(os.getcwd(), "labelled_templates")]
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(os.path.dirname(sys.executable), "labelled_templates"))
    else:
        dirs.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "labelled_templates"))
    return dirs
