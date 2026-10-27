"""Phase 2 (final): adjust each placeholder's crop PowerPoint-style, then save the PNG."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .. import crop as cropmod
from .. import geometry, instagram
from ..crop import CropBox
from ..imageio import image_size, open_reduced
from ..models import LabelledTemplate
from ..render import render
from .common import BusyOverlay, run_bg

MAX_SIDE = 1600
CORNERS = ("nw", "ne", "se", "sw")
CORNER_CURSOR = {"nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw"}


class CropperFrame(ttk.Frame):
    def __init__(self, master, lt: LabelledTemplate, assignments: dict[int, str], tolerance: float,
                 output_dir: str, on_back, name: str = "collage", on_saved=None):
        super().__init__(master)
        self.on_saved = on_saved
        self.lt, self.assignments, self.tol = lt, assignments, tolerance
        self.output_dir, self.on_back, self.name = output_dir, on_back, name
        self.items: dict[int, tuple[str, CropBox]] = {}
        self.autos: dict[int, CropBox] = {}
        self.imgs: dict[str, tuple[Image.Image, tuple[float, float]]] = {}
        self.osizes: dict[str, tuple[int, int]] = {}
        self.sel: int | None = None
        self._drag: dict | None = None
        self._cphoto = None
        self._cphoto_key = None
        self._pphoto = None
        self._pscale = 1.0
        self._poff = (0.0, 0.0)
        self._cscale = 1.0
        self._coff = (0.0, 0.0)
        self._comp: Image.Image | None = None
        self._comp_scale = None
        self._pending = None

        self.busy = BusyOverlay(self, "Finding best crops...")
        self.busy.pack(fill="both", expand=True)
        run_bg(self, self._compute, self._built, self.busy.progress, self.busy.label)

    # ---------- background: load images + auto crop
    def _compute(self, report):
        n = len(self.assignments)
        failures: list[str] = []
        for k, (pid, path) in enumerate(self.assignments.items()):
            report(k / n, f"{k + 1}/{n}")
            try:
                if path not in self.imgs:
                    osize = image_size(path)
                    self.imgs[path] = open_reduced(path, MAX_SIDE)
                    self.osizes[path] = osize
                img, (fx, fy) = self.imgs[path]
                ow, oh = self.osizes[path]
                ph = self.lt.get(pid)
                _, _, iw, ih = ph.inset
                ar = iw / ih
                small = cropmod.auto_crop(img, ar, self.tol)
                box = cropmod.fit_box(CropBox(small.x / fx, small.y / fy, small.w / fx, small.h / fy), ow, oh, ar)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{os.path.basename(path)}: {e}")
                continue
            self.autos[pid] = box
            self.items[pid] = (path, CropBox(box.x, box.y, box.w, box.h))
            report((k + 1) / n, f"{k + 1}/{n}")
        return failures

    def _built(self, failures, err) -> None:
        if err or failures:
            msg = str(err) if err else "These images could not be used:\n\n" + "\n".join(failures[:12])
            messagebox.showerror("Cannot load images", msg + "\n\nPick different images.", parent=self)
            self.on_back()
            return
        self.busy.destroy()
        self._build()
        first = min(self.items) if self.items else None
        self._select(first)

    # ---------- layout
    def _build(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)
        self.pcanvas = tk.Canvas(self, background="#2b2b2b", highlightthickness=0)
        self.pcanvas.grid(row=0, column=0, sticky="nsew")
        self.pcanvas.bind("<Configure>", lambda e: self._preview_resize())
        self.pcanvas.bind("<Button-1>", self._preview_click)

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        self.title = tk.StringVar()
        ttk.Label(right, textvariable=self.title, font=("", 10, "bold")).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.ccanvas = tk.Canvas(right, background="#1e1e1e", highlightthickness=0)
        self.ccanvas.grid(row=1, column=0, sticky="nsew")
        self.ccanvas.bind("<Configure>", lambda e: self._draw_crop())
        self.ccanvas.bind("<ButtonPress-1>", self._cpress)
        self.ccanvas.bind("<B1-Motion>", self._cmotion)
        self.ccanvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.ccanvas.bind("<Motion>", self._chover)
        self.ccanvas.bind("<MouseWheel>", self._cwheel)
        ttk.Label(
            right, foreground="#555", wraplength=330,
            text="Drag inside the frame to move the crop, drag a corner to resize, mouse wheel to zoom.",
        ).grid(row=2, column=0, sticky="w", padx=6, pady=4)
        row = ttk.Frame(right)
        row.grid(row=3, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(row, text="Reset to auto", command=self._reset).pack(side="left")
        ttk.Button(row, text="← Back", command=self.on_back).pack(side="left", padx=6)
        ttk.Button(row, text="Save PNG", command=self._save).pack(side="right")

    # ---------- preview (collage)
    def _preview_resize(self) -> None:
        cw, ch = self.pcanvas.winfo_width(), self.pcanvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        W, H = self.lt.size
        s = min(cw / W, ch / H) * 0.98
        if self._comp_scale is None or abs(s - self._comp_scale) > 1e-6:
            self._comp_scale = s
            base = Image.open(self.lt.template_path).convert("RGBA")
            base = base.resize((max(1, round(W * s)), max(1, round(H * s))), Image.LANCZOS)
            self._comp = render(self.lt, self.items, scale=s, base=base, getter=lambda p: self.imgs[p])
        self._pscale = s
        self._poff = ((cw - W * s) / 2, (ch - H * s) / 2)
        self._draw_preview()

    def _draw_preview(self) -> None:
        if self._comp is None:
            return
        c = self.pcanvas
        c.delete("all")
        self._pphoto = ImageTk.PhotoImage(self._comp)
        c.create_image(self._poff[0], self._poff[1], image=self._pphoto, anchor="nw")
        for ph in self.lt.placeholders:
            s, o = self._pscale, self._poff
            sel = ph.id == self.sel
            c.create_rectangle(o[0] + ph.x * s, o[1] + ph.y * s, o[0] + (ph.x + ph.w) * s, o[1] + (ph.y + ph.h) * s,
                               outline="#ffcc00" if sel else "#ffffff", width=3 if sel else 1,
                               dash=() if sel else (3, 4))

    def _preview_click(self, e) -> None:
        x = (e.x - self._poff[0]) / self._pscale
        y = (e.y - self._poff[1]) / self._pscale
        for ph in reversed(self.lt.placeholders):
            if ph.id in self.items and ph.x <= x <= ph.x + ph.w and ph.y <= y <= ph.y + ph.h:
                self._select(ph.id)
                return

    def _refresh_one(self, pid: int) -> None:
        if self._comp is None:
            return
        self._comp = render(self.lt, self.items, scale=self._comp_scale, base=self._comp,
                            getter=lambda p: self.imgs[p], only={pid})
        self._draw_preview()

    # ---------- crop panel
    def _select(self, pid: int | None) -> None:
        self.sel = pid
        if pid is not None:
            ph = self.lt.get(pid)
            self.title.set(f"#{pid} {ph.tag} — {os.path.basename(self.items[pid][0])}")
        self._cphoto_key = None
        self._draw_crop()
        self._draw_preview()

    def _osize(self, path: str) -> tuple[float, float]:
        return self.osizes[path]

    def _draw_crop(self) -> None:
        c = self.ccanvas
        c.delete("all")
        if self.sel is None:
            return
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 10 or ch < 10:
            return
        path, box = self.items[self.sel]
        iw, ih = self._osize(path)
        s = min(cw / iw, ch / ih) * 0.96
        self._cscale = s
        self._coff = ((cw - iw * s) / 2, (ch - ih * s) / 2)
        key = (path, round(s, 4))
        if key != self._cphoto_key:
            img = self.imgs[path][0].resize((max(1, round(iw * s)), max(1, round(ih * s))), Image.BILINEAR)
            self._cphoto = ImageTk.PhotoImage(img)
            self._cphoto_key = key
        ox, oy = self._coff
        c.create_image(ox, oy, image=self._cphoto, anchor="nw")
        x0, y0 = ox + box.x * s, oy + box.y * s
        x1, y1 = x0 + box.w * s, y0 + box.h * s
        ex, ey = ox + iw * s, oy + ih * s
        for r in ((ox, oy, ex, y0), (ox, y1, ex, ey), (ox, y0, x0, y1), (x1, y0, ex, y1)):
            c.create_rectangle(*r, fill="black", stipple="gray50", outline="")
        c.create_rectangle(x0, y0, x1, y1, outline="white", width=2)
        for i in (1, 2):
            c.create_line(x0 + (x1 - x0) * i / 3, y0, x0 + (x1 - x0) * i / 3, y1, fill="white", stipple="gray25")
            c.create_line(x0, y0 + (y1 - y0) * i / 3, x1, y0 + (y1 - y0) * i / 3, fill="white", stipple="gray25")
        for hx, hy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            c.create_rectangle(hx - 5, hy - 5, hx + 5, hy + 5, fill="white", outline="black")

    def _to_img(self, sx: float, sy: float) -> tuple[float, float]:
        return ((sx - self._coff[0]) / self._cscale, (sy - self._coff[1]) / self._cscale)

    def _hit(self, e) -> str | None:
        if self.sel is None:
            return None
        _, box = self.items[self.sel]
        px, py = self._to_img(e.x, e.y)
        hit = geometry.hit_test((box.x, box.y, box.w, box.h), px, py, 10 / self._cscale)
        return hit if hit in CORNERS or hit == "move" else None

    def _chover(self, e) -> None:
        hit = self._hit(e)
        try:
            self.ccanvas.configure(cursor=CORNER_CURSOR.get(hit, "fleur" if hit == "move" else ""))
        except tk.TclError:
            self.ccanvas.configure(cursor="")

    def _cpress(self, e) -> None:
        hit = self._hit(e)
        if hit is None:
            return
        px, py = self._to_img(e.x, e.y)
        self._drag = {"hit": hit, "start": (px, py), "box": self.items[self.sel][1]}

    def _set_box(self, box: CropBox) -> None:
        pid = self.sel
        path = self.items[pid][0]
        _, _, iw, ih = self.lt.get(pid).inset
        ow, oh = self._osize(path)
        box = cropmod.fit_box(box, ow, oh, iw / ih)  # guard: always inside the image, exact aspect
        self.items[pid] = (path, box)
        self._draw_crop()
        self._schedule_preview(pid)

    def _cmotion(self, e) -> None:
        d = self._drag
        if not d or self.sel is None:
            return
        path = self.items[self.sel][0]
        iw, ih = self._osize(path)
        px, py = self._to_img(e.x, e.y)
        b = d["box"]
        if d["hit"] == "move":
            box = cropmod.pan(b, px - d["start"][0], py - d["start"][1], iw, ih)
        else:
            box = cropmod.resize_corner(b, d["hit"], px, py, iw, ih)
        self._set_box(box)

    def _cwheel(self, e) -> None:
        if self.sel is None:
            return
        path, box = self.items[self.sel]
        iw, ih = self._osize(path)
        px, py = self._to_img(e.x, e.y)
        anchor = (px, py) if box.x <= px <= box.x + box.w and box.y <= py <= box.y + box.h else None
        self._set_box(cropmod.zoom(box, 1.1 if e.delta > 0 else 1 / 1.1, iw, ih, anchor))

    def _reset(self) -> None:
        if self.sel is not None:
            b = self.autos[self.sel]
            self._set_box(CropBox(b.x, b.y, b.w, b.h))

    def _schedule_preview(self, pid: int) -> None:
        if self._pending is not None:
            return

        def go():
            self._pending = None
            self._refresh_one(pid)

        self._pending = self.after(40, go)

    # ---------- save
    def _save(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self, initialdir=self.output_dir, initialfile=f"{self.name}_collage.png",
            defaultextension=".png", filetypes=[("PNG image", "*.png")],
        )
        if not path:
            return

        def work(report):
            report(0.1, "Rendering...")
            problems: list[str] = []
            out = render(self.lt, self.items, errors=problems)
            if problems:
                raise RuntimeError("Not saved:\n" + "\n".join(problems[:10]))
            report(0.8, "Saving...")
            out.save(path, "PNG")

        def done(_res, err):
            if err:
                messagebox.showerror("Save failed", str(err), parent=self)
                return
            if self.on_saved:
                self.on_saved(path)
            msg = f"Saved {path}"
            warn = instagram.check_file_size(path)
            messagebox.showinfo("Saved", msg + (f"\n\n{warn}" if warn else ""), parent=self)

        run_bg(self, work, done)
