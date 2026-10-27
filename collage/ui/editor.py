"""Phase 1: place and label collage placeholders on the template."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .. import geometry
from ..models import LabelledTemplate, Placeholder, rename_labelled, save_labelled, unique_path
from .common import tag_color

CURSORS = {
    "nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw",
    "n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we", "move": "fleur",
}
SNAP_PX = 8  # screen pixels
HANDLE_PX = 7
SHIFT, CTRL, ALT = 0x1, 0x4, 0x20000  # event.state masks (Alt: Windows)
BIG_SPLIT = 36

ALIGN_BUTTONS = [
    ("⭰ Left", "left"), ("↔ Centre", "center"), ("Right ⭲", "right"),
    ("⭱ Top", "top"), ("↕ Middle", "middle"), ("Bottom ⭳", "bottom"),
]


def _intersects(a: geometry.Rect, b: geometry.Rect) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class SplitDialog(tk.Toplevel):
    """Rows / cols / gap with a live preview drawn by the editor."""

    def __init__(self, editor: "TemplateEditor", ph: Placeholder):
        super().__init__(editor)
        self.editor, self.ph = editor, ph
        self.result: list[geometry.Rect] | None = None
        self.title("Split into grid")
        self.transient(editor.winfo_toplevel())
        self.resizable(False, False)
        self.rows, self.cols, self.gap = tk.StringVar(value="2"), tk.StringVar(value="2"), tk.StringVar(value="0")
        f = ttk.Frame(self, padding=12)
        f.pack()
        for i, (label, var, lo) in enumerate((("Rows", self.rows, 1), ("Columns", self.cols, 1), ("Gap (px)", self.gap, 0))):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=3)
            sb = ttk.Spinbox(f, from_=lo, to=999, width=7, textvariable=var, command=self._update)
            sb.grid(row=i, column=1, padx=8)
            var.trace_add("write", lambda *_: self._update())
        self.info = tk.StringVar()
        ttk.Label(f, textvariable=self.info, foreground="#a33", wraplength=220).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=4, column=0, columnspan=2, sticky="e", pady=(6, 0))
        self.ok = ttk.Button(row, text="Split", command=self._ok)
        self.ok.pack(side="left", padx=4)
        ttk.Button(row, text="Cancel", command=self._cancel).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())
        self._update()
        self.grab_set()

    def _cells(self) -> list[geometry.Rect] | None:
        try:
            r, c, g = int(self.rows.get()), int(self.cols.get()), int(self.gap.get())
            cells = geometry.split_grid(self.ph.rect, r, c, g)
        except ValueError as e:
            self.info.set(str(e) if "small" in str(e) or "must" in str(e) else "Enter whole numbers.")
            return None
        self.info.set(f"{len(cells)} cells, about {round(cells[0][2])}×{round(cells[0][3])} px each")
        return cells

    def _update(self) -> None:
        cells = self._cells()
        self.ok.configure(state="normal" if cells else "disabled")
        self.editor.set_split_preview(cells)

    def _ok(self) -> None:
        cells = self._cells()
        if not cells:
            return
        if len(cells) > BIG_SPLIT and not messagebox.askyesno(
            "Many placeholders", f"This creates {len(cells)} placeholders. Continue?", parent=self
        ):
            return
        self.result = cells
        self._close()

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        self.editor.set_split_preview(None)
        self.grab_release()
        self.destroy()


class TemplateEditor(ttk.Frame):
    def __init__(
        self,
        master,
        lt: LabelledTemplate,
        tags: list[str],
        save_dir: str,
        on_continue=None,
        on_back=None,
        existing_path: str | None = None,
        continue_text: str = "Continue →",
        default_padding: int = 0,
    ):
        super().__init__(master)
        self.default_padding = default_padding
        self.lt = lt
        self.tags = [t for t in tags if t]
        self.save_dir = save_dir
        self.on_continue = on_continue
        self.on_back = on_back
        self.path = existing_path
        self.img = Image.open(lt.template_path).convert("RGB")
        self.sel: set[int] = set()
        self._photo = None
        self._photo_key = None
        self.scale = 1.0
        self.off = (0.0, 0.0)
        self._drag: dict | None = None
        self._updating = False
        self._split_preview: list[geometry.Rect] | None = None
        self._marquee: geometry.Rect | None = None
        self.last_tag = self.tags[0] if self.tags else ""

        self.lock = tk.BooleanVar(value=False)
        self.draw_mode = tk.BooleanVar(value=False)
        self.align_canvas = tk.BooleanVar(value=False)
        self.vars = {k: tk.StringVar() for k in "xywh"}
        self.tag_var = tk.StringVar()
        self.pad_var = tk.StringVar(value="0")
        stem = os.path.splitext(os.path.basename(existing_path or lt.template_path))[0]
        self.name_var = tk.StringVar(value=stem)
        self.status = tk.StringVar()
        self._set_default_status()

        self._build(continue_text)
        self._refresh_list()
        self.bind("<Configure>", lambda e: self.redraw())

    # ---------- layout
    def _build(self, continue_text: str) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background="#2b2b2b", highlightthickness=0, cursor="arrow")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        top = self.winfo_toplevel()
        top.bind("<Delete>", self._delete_key, add="+")
        top.bind("<Control-a>", self._select_all_key, add="+")

        outer = ttk.Frame(self)
        outer.grid(row=0, column=1, sticky="ns")
        side = ttk.Frame(outer, padding=8)
        side.pack(fill="y", expand=True)

        ttk.Checkbutton(side, text="Draw mode (drag to add)", variable=self.draw_mode, style="Toolbutton",
                        command=self._mode_changed).pack(fill="x")
        ttk.Label(side, text="Placeholders", font=("", 11, "bold")).pack(anchor="w", pady=(8, 0))
        self.listbox = tk.Listbox(side, height=8, exportselection=False, activestyle="none", selectmode="extended")
        self.listbox.pack(fill="x", pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._list_select)

        grid = ttk.Frame(side)
        grid.pack(fill="x", pady=2)
        self.spins = []
        for i, k in enumerate("xywh"):
            ttk.Label(grid, text=k.upper()).grid(row=i // 2, column=(i % 2) * 2, padx=(0, 2), pady=2)
            sb = ttk.Spinbox(grid, from_=0, to=99999, increment=1, width=7, textvariable=self.vars[k],
                             command=lambda k=k: self._apply_field(k))
            sb.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(0, 8), pady=2)
            sb.bind("<Return>", lambda e, k=k: self._apply_field(k))
            sb.bind("<FocusOut>", lambda e, k=k: self._apply_field(k))
            self.spins.append(sb)
        ttk.Checkbutton(side, text="Lock aspect ratio", variable=self.lock).pack(anchor="w", pady=2)

        ttk.Label(side, text="Tag").pack(anchor="w")
        self.tag_box = ttk.Combobox(side, textvariable=self.tag_var, values=self.tags, state="readonly")
        self.tag_box.pack(fill="x", pady=(0, 2))
        self.tag_box.bind("<<ComboboxSelected>>", self._tag_changed)
        ttk.Button(side, text="New tag...", command=self._new_tag).pack(anchor="w", pady=(0, 4))

        prow = ttk.Frame(side)
        prow.pack(fill="x", pady=2)
        ttk.Label(prow, text="Padding (px)").pack(side="left")
        self.pad_spin = ttk.Spinbox(prow, from_=0, to=999, width=6, textvariable=self.pad_var)
        self.pad_spin.pack(side="left", padx=6)
        self.pad_btn = ttk.Button(prow, text="Apply", width=7, command=self._apply_padding)
        self.pad_btn.pack(side="left")
        self.pad_spin.bind("<Return>", lambda e: self._apply_padding())

        self.split_btn = ttk.Button(side, text="Split into grid...", command=self._split)
        self.split_btn.pack(fill="x", pady=(4, 0))
        ttk.Button(side, text="Delete selected", command=self._delete_sel).pack(fill="x", pady=(4, 0))

        al = ttk.LabelFrame(side, text="Align / distribute", padding=4)
        al.pack(fill="x", pady=(8, 0))
        self.align_btns = []
        for i, (text, how) in enumerate(ALIGN_BUTTONS):
            b = ttk.Button(al, text=text, width=9, command=lambda h=how: self._align(h))
            b.grid(row=i // 3, column=i % 3, padx=1, pady=1)
            self.align_btns.append(b)
        self.dist_btns = [
            ttk.Button(al, text="Distribute ↔", command=lambda: self._distribute("h")),
            ttk.Button(al, text="Distribute ↕", command=lambda: self._distribute("v")),
        ]
        self.dist_btns[0].grid(row=2, column=0, columnspan=2, sticky="ew", padx=1, pady=1)
        self.dist_btns[1].grid(row=2, column=2, sticky="ew", padx=1, pady=1)
        ttk.Checkbutton(al, text="Align to canvas", variable=self.align_canvas, command=self._sync_fields).grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="Template name").pack(anchor="w")
        ttk.Entry(side, textvariable=self.name_var).pack(fill="x", pady=(0, 4))
        row = ttk.Frame(side)
        row.pack(fill="x")
        ttk.Button(row, text="Save", command=self.save).pack(side="left", expand=True, fill="x")
        self.rename_btn = ttk.Button(row, text="Rename", command=self._rename, state="disabled" if not self.path else "normal")
        self.rename_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))
        if self.on_continue:
            ttk.Button(side, text=continue_text, command=self._continue).pack(fill="x", pady=(8, 0))
        if self.on_back:
            ttk.Button(side, text="← Back", command=self.on_back).pack(fill="x", pady=(4, 0))
        ttk.Label(side, textvariable=self.status, wraplength=250, foreground="#555").pack(anchor="w", pady=6)

    def _set_default_status(self) -> None:
        if self.draw_mode.get():
            self.status.set("Draw mode: drag on the template to add a placeholder. Hold Alt to disable snapping.")
        else:
            self.status.set("Click to select (Shift/Ctrl+click adds), drag empty space to box-select, Ctrl+A selects all. "
                            "Ctrl+drag draws. Alt disables snapping.")

    def _mode_changed(self) -> None:
        self._set_default_status()
        self._update_cursor(None)

    # ---------- helpers
    def _to_img(self, sx: float, sy: float) -> tuple[float, float]:
        return ((sx - self.off[0]) / self.scale, (sy - self.off[1]) / self.scale)

    def _to_scr(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.off[0], y * self.scale + self.off[1])

    def _thr(self, event=None) -> float:
        if event is not None and event.state & ALT:
            return 0.0
        return SNAP_PX / self.scale

    def _others(self, skip: set[int] | int | None) -> list[geometry.Rect]:
        skip = {skip} if isinstance(skip, int) else (skip or set())
        return [p.rect for p in self.lt.placeholders if p.id not in skip]

    def _selected(self) -> list[Placeholder]:
        return [p for p in self.lt.placeholders if p.id in self.sel]

    def _single(self) -> Placeholder | None:
        return self.lt.get(next(iter(self.sel))) if len(self.sel) == 1 else None

    def _clamp_rect(self, r: geometry.Rect) -> geometry.Rect:
        W, H = self.lt.size
        x, y, w, h = r
        w, h = min(w, W), min(h, H)
        return (min(max(x, 0), W - w), min(max(y, 0), H - h), w, h)

    # ---------- drawing
    def set_split_preview(self, cells) -> None:
        self._split_preview = cells
        self.redraw()

    def redraw(self) -> None:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        iw, ih = self.img.size
        self.scale = min(cw / iw, ch / ih) * 0.98
        self.off = ((cw - iw * self.scale) / 2, (ch - ih * self.scale) / 2)
        key = round(self.scale, 4)
        if key != self._photo_key:
            disp = self.img.resize((max(1, round(iw * self.scale)), max(1, round(ih * self.scale))), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(disp)
            self._photo_key = key
        c = self.canvas
        c.delete("all")
        c.create_image(self.off[0], self.off[1], image=self._photo, anchor="nw")
        for ph in self.lt.placeholders:
            self._draw_ph(ph)
        if len(self.sel) > 1:
            x0, y0, x1, y1 = self._scr_rect(geometry.bounds([p.rect for p in self._selected()]))
            c.create_rectangle(x0, y0, x1, y1, outline="white", dash=(5, 3))
        for cell in self._split_preview or []:
            x0, y0, x1, y1 = self._scr_rect(cell)
            c.create_rectangle(x0, y0, x1, y1, outline="#00e5ff", width=2, dash=(4, 2))
        if self._marquee:
            x0, y0, x1, y1 = self._scr_rect(self._marquee)
            c.create_rectangle(x0, y0, x1, y1, outline="#4da3ff", fill="#4da3ff", stipple="gray12")

    def _scr_rect(self, r: geometry.Rect) -> tuple[float, float, float, float]:
        x0, y0 = self._to_scr(r[0], r[1])
        x1, y1 = self._to_scr(r[0] + r[2], r[1] + r[3])
        return x0, y0, x1, y1

    def _color(self, ph: Placeholder) -> str:
        return tag_color(self.lt, ph.tag)

    def _draw_ph(self, ph: Placeholder) -> None:
        c = self.canvas
        x0, y0, x1, y1 = self._scr_rect(ph.rect)
        col = self._color(ph)
        selected = ph.id in self.sel
        c.create_rectangle(x0, y0, x1, y1, outline=col, width=3 if selected else 2, fill=col, stipple="gray25")
        if ph.padding:
            c.create_rectangle(*self._scr_rect(ph.inset), outline="white", dash=(3, 3))
        label = f"#{ph.id} {ph.tag}"
        c.create_text(x0 + 4, y0 + 3, text=label, anchor="nw", fill="white", font=("", 9, "bold"))
        if selected and len(self.sel) == 1:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            pts = [(x0, y0), (cx, y0), (x1, y0), (x1, cy), (x1, y1), (cx, y1), (x0, y1), (x0, cy)]
            for hx, hy in pts:
                c.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill="white", outline="black")

    # ---------- selection / panel sync
    def _refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        for i, ph in enumerate(self.lt.placeholders):
            pad = f" p{ph.padding}" if ph.padding else ""
            self.listbox.insert("end", f"#{ph.id}  {ph.tag}  {round(ph.w)}x{round(ph.h)}{pad}")
            if ph.id in self.sel:
                self.listbox.selection_set(i)
        self._sync_fields()

    def _sync_fields(self) -> None:
        one = self._single()
        n = len(self.sel)
        self._updating = True
        for k in "xywh":
            self.vars[k].set("" if one is None else str(round(getattr(one, k))))
        tags = {p.tag for p in self._selected()}
        self.tag_var.set(next(iter(tags)) if len(tags) == 1 else "")
        pads = {p.padding for p in self._selected()}
        self.pad_var.set(str(next(iter(pads))) if len(pads) == 1 else ("" if pads else "0"))
        self._updating = False
        st = "normal" if one else "disabled"
        for sb in self.spins:
            sb.configure(state=st)
        self.split_btn.configure(state=st)
        self.pad_btn.configure(state="normal" if n else "disabled")
        self.tag_box.configure(state="readonly" if n else "disabled")
        for b in self.align_btns:
            b.configure(state="normal" if n >= 2 or (n == 1 and self.align_canvas.get()) else "disabled")
        for b in self.dist_btns:
            b.configure(state="normal" if n >= 3 else "disabled")

    def _set_sel(self, ids) -> None:
        self.sel = set(ids)
        self._refresh_list()
        self.redraw()

    def _list_select(self, _e=None) -> None:
        idx = self.listbox.curselection()
        self.sel = {self.lt.placeholders[i].id for i in idx}
        self._sync_fields()
        self.redraw()

    def _select_all_key(self, e) -> str | None:
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return None
        if self.winfo_ismapped():
            self._set_sel(p.id for p in self.lt.placeholders)
            return "break"
        return None

    def _apply_field(self, key: str) -> None:
        if self._updating:
            return
        ph = self._single()
        if ph is None:
            return
        try:
            v = float(self.vars[key].get())
        except ValueError:
            self._sync_fields()
            return
        ph.rect = geometry.set_field(ph.rect, key, v, self.lock.get(), self.lt.size)
        self._refresh_list()
        self.redraw()

    def _new_tag(self) -> None:
        """Tags are names the user chooses; each one gets its own image folder later."""
        tag = simpledialog.askstring("New tag", "Tag name (e.g. 'artwork', 'profile pic'):", parent=self)
        tag = (tag or "").strip()
        if not tag:
            return
        if tag not in self.tags:
            self.tags = self.tags + [tag]
            self.tag_box.configure(values=self.tags)
        self.tag_var.set(tag)
        self._tag_changed()

    def _tag_changed(self, _e=None) -> None:
        tag = self.tag_var.get()
        for ph in self._selected():
            ph.tag = tag
        if self.sel:
            self.last_tag = tag
            self._refresh_list()
            self.redraw()

    def _apply_padding(self) -> None:
        try:
            p = int(float(self.pad_var.get()))
        except ValueError:
            self._sync_fields()
            return
        p = max(0, p)
        for ph in self._selected():
            ph.padding = min(p, int((min(ph.w, ph.h) - 1) // 2))
        self._refresh_list()
        self.redraw()

    def _delete_key(self, e) -> None:
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return
        try:
            if self.winfo_ismapped():
                self._delete_sel()
        except tk.TclError:  # editor already destroyed
            pass

    def _delete_sel(self) -> None:
        if not self.sel:
            return
        self.lt.placeholders = [p for p in self.lt.placeholders if p.id not in self.sel]
        self._set_sel(())

    # ---------- split / align / distribute
    def _split(self) -> None:
        ph = self._single()
        if ph is None:
            return
        dlg = SplitDialog(self, ph)
        self.wait_window(dlg)
        if not dlg.result:
            return
        idx = self.lt.placeholders.index(ph)
        new_ids = []
        nid = self.lt.next_id()
        cells = []
        for r in dlg.result:
            cells.append(Placeholder(nid, *r, tag=ph.tag, padding=ph.padding))
            new_ids.append(nid)
            nid += 1
        self.lt.placeholders[idx:idx + 1] = cells
        self._set_sel(new_ids)
        self.status.set(f"Split into {len(cells)} placeholders.")

    def _align(self, how: str) -> None:
        phs = self._selected()
        if not phs:
            return
        W, H = self.lt.size
        ref = (0, 0, W, H) if self.align_canvas.get() else None
        for ph, r in zip(phs, geometry.align([p.rect for p in phs], how, ref)):
            ph.rect = self._clamp_rect(r)
        self._refresh_list()
        self.redraw()

    def _distribute(self, axis: str) -> None:
        phs = self._selected()
        if len(phs) < 3:
            return
        for ph, r in zip(phs, geometry.distribute([p.rect for p in phs], axis)):
            ph.rect = self._clamp_rect(r)
        self._refresh_list()
        self.redraw()

    # ---------- mouse
    def _update_cursor(self, e) -> None:
        cur = "arrow"
        if self.draw_mode.get():
            cur = "crosshair"
        elif e is not None:
            px, py = self._to_img(e.x, e.y)
            one = self._single()
            hit = geometry.hit_test(one.rect, px, py, HANDLE_PX / self.scale) if one else None
            if hit is None:
                top = self._ph_at(px, py)
                hit = "move" if top and top.id in self.sel else None
            cur = CURSORS.get(hit, "arrow")
        try:
            self.canvas.configure(cursor=cur)
        except tk.TclError:
            self.canvas.configure(cursor="arrow")

    def _hover(self, e) -> None:
        self._update_cursor(e)

    def _ph_at(self, px: float, py: float) -> Placeholder | None:
        for ph in reversed(self.lt.placeholders):
            x, y, w, h = ph.rect
            if x <= px <= x + w and y <= py <= y + h:
                return ph
        return None

    def _snap_pt(self, px: float, py: float, e) -> tuple[float, float]:
        W, H = self.lt.size
        xs, ys = geometry._targets(self._others(None), self.lt.size)
        thr = self._thr(e)
        return (geometry.snap_value(min(max(px, 0), W), xs, thr), geometry.snap_value(min(max(py, 0), H), ys, thr))

    def _start_move(self, px: float, py: float) -> None:
        self._drag = {"mode": "move", "start": (px, py), "rects": {p.id: p.rect for p in self._selected()}}

    def _press(self, e) -> None:
        px, py = self._to_img(e.x, e.y)
        additive = bool(e.state & (SHIFT | CTRL))
        drawing = self.draw_mode.get() or bool(e.state & CTRL and self._ph_at(px, py) is None)
        one = self._single()
        if one and not self.draw_mode.get() and not (e.state & SHIFT):
            hit = geometry.hit_test(one.rect, px, py, HANDLE_PX / self.scale)
            if hit and hit != "move":
                self._drag = {"mode": "resize", "handle": hit, "id": one.id, "rect": one.rect}
                return
        if not self.draw_mode.get():
            top = self._ph_at(px, py)
            if top is not None:
                if additive:
                    self._set_sel(self.sel ^ {top.id})
                    self._drag = None
                    return
                if top.id not in self.sel:
                    self._set_sel({top.id})
                self._start_move(px, py)
                return
        if drawing:
            self._set_sel(())
            self._drag = {"mode": "draw", "start": self._snap_pt(px, py, e), "rect": None}
            return
        base = set(self.sel) if additive else set()
        if not additive:
            self._set_sel(())
        self._drag = {"mode": "marquee", "start": (px, py), "base": base}

    def _motion(self, e) -> None:
        d = self._drag
        if not d:
            return
        px, py = self._to_img(e.x, e.y)
        thr = self._thr(e)
        mode = d["mode"]
        if mode == "draw":
            qx, qy = self._snap_pt(px, py, e)
            sx, sy = d["start"]
            d["rect"] = (min(sx, qx), min(sy, qy), abs(qx - sx), abs(qy - sy))
            self._marquee = d["rect"]
            self.redraw()
            return
        if mode == "marquee":
            sx, sy = d["start"]
            m = (min(sx, px), min(sy, py), abs(px - sx), abs(py - sy))
            self._marquee = m
            hit = {p.id for p in self.lt.placeholders if _intersects(p.rect, m)}
            new = d["base"] | hit
            if new != self.sel:
                self.sel = new
                self._sync_fields()
            self.redraw()
            return
        if mode == "move":
            rects = d["rects"]
            dx, dy = px - d["start"][0], py - d["start"][1]
            dx, dy = geometry.snap_move_group(list(rects.values()), dx, dy, self._others(set(rects)), self.lt.size, thr)
            for pid, (x, y, w, h) in rects.items():
                ph = self.lt.get(pid)
                if ph:
                    ph.rect = (x + dx, y + dy, w, h)
        else:
            ph = self.lt.get(d["id"])
            if ph is None:
                return
            ph.rect = geometry.resize_rect(
                d["rect"], d["handle"], px, py, self._others(ph.id), self.lt.size, self.lock.get(), thr
            )
        self._sync_fields()
        self.redraw()

    def _release(self, e) -> None:
        d, self._drag = self._drag, None
        self._marquee = None
        if not d:
            return
        if d["mode"] == "draw":
            r = d["rect"]
            if r and r[2] >= 10 and r[3] >= 10:
                ph = Placeholder(self.lt.next_id(), *r, tag=self.last_tag,
                                 padding=min(self.default_padding, int((min(r[2], r[3]) - 1) // 2)))
                self.lt.placeholders.append(ph)
                self._set_sel({ph.id})
                if not self.last_tag:  # no tag exists yet: name it now
                    self.after_idle(self._new_tag)
                return
            self.redraw()
            return
        if d["mode"] == "marquee":
            self._refresh_list()
            self.redraw()
            return
        self._refresh_list()

    # ---------- persistence
    def _round(self) -> None:
        for ph in self.lt.placeholders:
            ph.rect = tuple(float(round(v)) for v in ph.rect)

    def save(self) -> str | None:
        if not self.lt.placeholders:
            messagebox.showwarning("Nothing to save", "Add at least one placeholder first.", parent=self)
            return None
        if any(not p.tag for p in self.lt.placeholders):
            messagebox.showwarning("Missing tag", "Every placeholder needs a tag.", parent=self)
            return None
        self._round()
        if self.path is None:
            self.path = unique_path(self.save_dir, self.name_var.get())
        save_labelled(self.lt, self.path)
        self.name_var.set(os.path.splitext(os.path.basename(self.path))[0])
        self.rename_btn.configure(state="normal")
        self.status.set(f"Saved {self.path}")
        return self.path

    def _rename(self) -> None:
        if not self.path:
            return
        try:
            self.path = rename_labelled(self.path, self.name_var.get())
        except FileExistsError:
            messagebox.showerror("Rename failed", "A template with that name already exists.", parent=self)
            return
        self.name_var.set(os.path.splitext(os.path.basename(self.path))[0])
        self.status.set(f"Renamed to {self.path}")

    def _continue(self) -> None:
        path = self.save()
        if path:
            self.on_continue(self.lt, path)
