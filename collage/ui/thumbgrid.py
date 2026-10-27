"""Scrollable thumbnail grid with ordered multi-select."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

CELL = 124
THUMB = 108


def _load_thumb(path: str):
    try:
        img = Image.open(path)
        if img.format == "JPEG":
            img.draft("RGB", (THUMB * 2, THUMB * 2))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((THUMB, THUMB))
        return img
    except Exception:  # noqa: BLE001
        return None


class ThumbGrid(ttk.Frame):
    def __init__(self, master, paths: list[str], limit: int, on_change=None):
        super().__init__(master)
        self.paths = paths
        self.limit = limit
        self.on_change = on_change
        self.selected: list[str] = []
        self._photos: dict[int, ImageTk.PhotoImage] = {}
        self._q: queue.Queue = queue.Queue()
        self._items: list[dict] = []
        self._stop = False

        self.canvas = tk.Canvas(self, highlightthickness=0, background="#f2f2f2")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self._layout())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        for i, p in enumerate(paths):
            rect = self.canvas.create_rectangle(0, 0, 0, 0, outline="#cccccc", width=2)
            img = self.canvas.create_image(0, 0, anchor="center")
            name = self.canvas.create_text(0, 0, text=os.path.basename(p)[:18], anchor="n", font=("", 7), fill="#444")
            badge = self.canvas.create_text(0, 0, text="", anchor="nw", font=("", 11, "bold"), fill="white")
            bbg = self.canvas.create_rectangle(0, 0, 0, 0, fill="", outline="", width=0)
            self.canvas.tag_lower(bbg, badge)
            self._items.append({"rect": rect, "img": img, "name": name, "badge": badge, "bbg": bbg})
        self._layout()
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(40, self._drain)

    # ---- loading
    def _worker(self) -> None:
        for i, p in enumerate(self.paths):
            if self._stop:
                return
            self._q.put((i, _load_thumb(p)))

    def _drain(self) -> None:
        if not self.winfo_exists():
            return
        for _ in range(8):
            try:
                i, img = self._q.get_nowait()
            except queue.Empty:
                break
            if img is not None:
                ph = ImageTk.PhotoImage(img)
                self._photos[i] = ph
                self.canvas.itemconfigure(self._items[i]["img"], image=ph)
        self.after(30, self._drain)

    def destroy(self) -> None:
        self._stop = True
        super().destroy()

    # ---- layout
    def _cols(self) -> int:
        return max(1, self.canvas.winfo_width() // CELL)

    def _layout(self) -> None:
        cols = self._cols()
        for i, it in enumerate(self._items):
            x, y = (i % cols) * CELL, (i // cols) * CELL
            self.canvas.coords(it["rect"], x + 4, y + 4, x + CELL - 4, y + CELL - 4)
            self.canvas.coords(it["img"], x + CELL / 2, y + 4 + THUMB / 2 + 2)
            self.canvas.coords(it["name"], x + CELL / 2, y + THUMB + 6)
            self.canvas.coords(it["badge"], x + 8, y + 6)
            self.canvas.coords(it["bbg"], x + 5, y + 5, x + 28, y + 26)
        rows = (len(self._items) + cols - 1) // cols
        self.canvas.configure(scrollregion=(0, 0, cols * CELL, max(1, rows) * CELL))

    def _wheel(self, e) -> None:
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    # ---- selection
    def _click(self, e) -> None:
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        cols = self._cols()
        c, r = int(x // CELL), int(y // CELL)
        if c >= cols:
            return
        i = r * cols + c
        if 0 <= i < len(self.paths):
            self.toggle(self.paths[i])

    def toggle(self, path: str) -> None:
        if path in self.selected:
            self.selected.remove(path)
        elif len(self.selected) < self.limit:
            self.selected.append(path)
        else:
            self.bell()
            return
        self._restyle()
        if self.on_change:
            self.on_change()

    def clear(self) -> None:
        self.selected.clear()
        self._restyle()
        if self.on_change:
            self.on_change()

    def _restyle(self) -> None:
        for i, p in enumerate(self.paths):
            it = self._items[i]
            if p in self.selected:
                n = self.selected.index(p) + 1
                self.canvas.itemconfigure(it["rect"], outline="#2a7de1", width=3)
                self.canvas.itemconfigure(it["badge"], text=str(n))
                self.canvas.itemconfigure(it["bbg"], fill="#2a7de1")
            else:
                self.canvas.itemconfigure(it["rect"], outline="#cccccc", width=2)
                self.canvas.itemconfigure(it["badge"], text="")
                self.canvas.itemconfigure(it["bbg"], fill="")
