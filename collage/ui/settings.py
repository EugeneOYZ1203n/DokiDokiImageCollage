"""Modal settings window."""
from __future__ import annotations

import dataclasses
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import INSTAGRAM_MODES, MAX_RECENT_LIMIT, Settings
from ..storage import Store

MODE_LABELS = {
    "ask": "Ask me",
    "resize": "Always resize to nearest",
    "never": "Never (use template size)",
}


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, store: Store, on_saved=None):
        super().__init__(master)
        self.store, self.on_saved = store, on_saved
        self.title("Settings")
        self.transient(master)
        self.resizable(False, False)
        s = store.settings

        self.output = tk.StringVar(value=s.output_dir)
        self.max_recent = tk.IntVar(value=s.max_recent_folders)
        self.tol = tk.DoubleVar(value=s.crop_tolerance)
        self.remember_save = tk.BooleanVar(value=s.remember_last_save_dir)
        self.mode = tk.StringVar(value=MODE_LABELS[s.instagram_size_mode])
        self.padding = tk.IntVar(value=s.default_padding)
        self.remember_win = tk.BooleanVar(value=s.remember_window)

        f = ttk.Frame(self, padding=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        r = 0

        ttk.Label(f, text="Default output folder").grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="ew", pady=4)
        ttk.Entry(row, textvariable=self.output, width=38).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left", padx=(6, 0))
        r += 1
        ttk.Label(f, text="(empty = " + store.default_output_dir + ")", foreground="gray").grid(
            row=r, column=1, sticky="w")
        r += 1

        ttk.Checkbutton(f, text="Remember last save location", variable=self.remember_save).grid(
            row=r, column=1, sticky="w", pady=4)
        r += 1

        ttk.Label(f, text="Remembered image folders (max)").grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="w", pady=4)
        ttk.Spinbox(row, from_=1, to=MAX_RECENT_LIMIT, width=5, textvariable=self.max_recent).pack(side="left")
        ttk.Button(row, text="Clear folder history", command=self._clear_history).pack(side="left", padx=8)
        r += 1

        ttk.Label(f, text="Crop tolerance").grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="ew", pady=4)
        self.tol_lbl = ttk.Label(row, width=5)
        ttk.Scale(row, from_=0.0, to=0.5, variable=self.tol, command=lambda _v: self._tol_text()).pack(
            side="left", fill="x", expand=True)
        self.tol_lbl.pack(side="left", padx=6)
        self._tol_text()
        r += 1
        ttk.Label(f, text="Max aspect-ratio difference that still gets a plain centre-fit crop; beyond it, a saliency crop is used.",
                  foreground="gray", wraplength=380).grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Label(f, text="Non-Instagram template size").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=self.mode, values=list(MODE_LABELS.values()), state="readonly").grid(
            row=r, column=1, sticky="w", pady=4)
        r += 1

        ttk.Label(f, text="Default placeholder padding (px)").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Spinbox(f, from_=0, to=200, width=5, textvariable=self.padding).grid(row=r, column=1, sticky="w", pady=4)
        r += 1

        ttk.Checkbutton(f, text="Remember window size and position", variable=self.remember_win).grid(
            row=r, column=1, sticky="w", pady=4)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=2, sticky="ew", pady=8)
        r += 1
        row = ttk.Frame(f)
        row.grid(row=r, column=0, columnspan=2, sticky="ew")
        ttk.Button(row, text="Open data folder", command=lambda: os.startfile(store.root)).pack(side="left")
        ttk.Button(row, text="Reset to defaults", command=self._reset).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Save", command=self._save).pack(side="right", padx=6)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _tol_text(self) -> None:
        self.tol_lbl.configure(text=f"{self.tol.get():.0%}")

    def _browse(self) -> None:
        d = filedialog.askdirectory(parent=self, title="Default output folder",
                                    initialdir=self.output.get() or self.store.default_output_dir)
        if d:
            self.output.set(os.path.normpath(d))

    def _clear_history(self) -> None:
        if messagebox.askyesno("Folder history", "Forget all remembered image folders?", parent=self):
            self.store.clear_recent()

    def _reset(self) -> None:
        d = Settings()
        self.output.set(d.output_dir)
        self.max_recent.set(d.max_recent_folders)
        self.tol.set(d.crop_tolerance)
        self._tol_text()
        self.remember_save.set(d.remember_last_save_dir)
        self.mode.set(MODE_LABELS[d.instagram_size_mode])
        self.padding.set(d.default_padding)
        self.remember_win.set(d.remember_window)

    def _save(self) -> None:
        try:
            raw = {
                "output_dir": self.output.get().strip(),
                "max_recent_folders": self.max_recent.get(),
                "crop_tolerance": self.tol.get(),
                "remember_last_save_dir": self.remember_save.get(),
                "instagram_size_mode": next(k for k in INSTAGRAM_MODES if MODE_LABELS[k] == self.mode.get()),
                "default_padding": self.padding.get(),
                "remember_window": self.remember_win.get(),
            }
        except tk.TclError:
            messagebox.showerror("Settings", "Enter whole numbers for the numeric fields.", parent=self)
            return
        cur = dataclasses.asdict(self.store.settings)
        cur.update(raw)
        self.store.set_settings(Settings.from_dict(cur))
        if self.on_saved:
            self.on_saved()
        self.destroy()
