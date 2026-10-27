"""Phase 2: choose images, manually or automatically (random / gradient / colour scheme)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import assign, colors
from ..imageio import list_images
from ..models import LabelledTemplate
from ..pools import load_pools
from .common import ColorButton, Tooltip, run_bg
from .thumbgrid import ThumbGrid

SCHEME_LABELS = {colors.ANY_SCHEME: "Any (best fit)", **{k: k.replace("-", " ").title() for k in colors.SCHEMES}}
LABEL_TO_SCHEME = {v: k for k, v in SCHEME_LABELS.items()}


class SelectionFrame(ttk.Frame):
    def __init__(self, master, lt: LabelledTemplate, folders: dict[str, str], color_cache: dict,
                 on_done, on_back):
        super().__init__(master, padding=8)
        self.lt, self.folders, self.cache = lt, folders, color_cache
        self.on_done, self.on_back = on_done, on_back
        self.tags = lt.tags_used()
        self._warned = False
        self._busy = False

        self.mode = tk.StringVar(value="manual")
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Image selection:", font=("", 11, "bold")).pack(side="left")
        ttk.Radiobutton(top, text="Manual", value="manual", variable=self.mode, command=self._switch).pack(side="left", padx=10)
        ttk.Radiobutton(top, text="Automatic", value="auto", variable=self.mode, command=self._switch).pack(side="left")
        ttk.Button(top, text="← Back", command=on_back).pack(side="right")

        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, pady=8)
        self.manual = self._build_manual(self.body)
        self.auto = self._build_auto(self.body)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x")
        self.progress = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar()
        ttk.Progressbar(bottom, variable=self.progress, maximum=100, length=220).pack(side="left")
        ttk.Label(bottom, textvariable=self.progress_text).pack(side="left", padx=8)
        self._switch()

    # ---------- mode switch
    def _switch(self) -> None:
        self.manual.pack_forget()
        self.auto.pack_forget()
        (self.manual if self.mode.get() == "manual" else self.auto).pack(fill="both", expand=True)

    # ---------- manual
    def _build_manual(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent)
        self.nb = ttk.Notebook(f)
        self.nb.pack(fill="both", expand=True)
        self.grids: dict[str, ThumbGrid] = {}
        for tag in self.tags:
            need = len(self.lt.by_tag(tag))
            page = ttk.Frame(self.nb)
            g = ThumbGrid(page, list_images(self.folders[tag]), need, on_change=self._manual_changed)
            g.pack(fill="both", expand=True)
            self.grids[tag] = g
            self.nb.add(page, text=f"{tag} (0/{need})")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="Clear tab", command=self._clear_tab).pack(side="left")
        self.manual_hint = tk.StringVar()
        ttk.Label(row, textvariable=self.manual_hint).pack(side="left", padx=10)
        self.manual_btn = ttk.Button(row, text="Continue to crop →", command=self._manual_done, state="disabled")
        self.manual_btn.pack(side="right")
        self._manual_changed()
        return f

    def _clear_tab(self) -> None:
        i = self.nb.index(self.nb.select())
        self.grids[self.tags[i]].clear()

    def _manual_changed(self) -> None:
        ok = True
        for i, tag in enumerate(self.tags):
            need = len(self.lt.by_tag(tag))
            have = len(self.grids[tag].selected)
            self.nb.tab(i, text=f"{tag} ({have}/{need})")
            ok &= have == need
        self.manual_btn.configure(state="normal" if ok else "disabled")
        self.manual_hint.set("" if ok else "Pick exactly as many images as there are placeholders for each tab.")

    def _manual_done(self) -> None:
        out = {}
        for tag in self.tags:
            for ph, path in zip(self.lt.by_tag(tag), self.grids[tag].selected):
                out[ph.id] = path
        self.on_done(out)

    # ---------- auto
    def _build_auto(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent)
        self.amode = tk.StringVar(value="random")
        r = ttk.LabelFrame(f, text="Method", padding=8)
        r.pack(fill="x")
        for text, val in (("Random", "random"), ("Gradient", "gradient"), ("Colour scheme", "scheme")):
            ttk.Radiobutton(r, text=text, value=val, variable=self.amode, command=self._auto_switch).pack(side="left", padx=8)

        self.opts = ttk.Frame(f)
        self.opts.pack(fill="x", pady=8)

        # gradient options
        self.g_frame = ttk.LabelFrame(self.opts, text="Gradient", padding=8)
        self.g_kind = tk.StringVar(value="linear")
        ttk.Radiobutton(self.g_frame, text="Linear", value="linear", variable=self.g_kind, command=self._auto_switch).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(self.g_frame, text="Radial", value="radial", variable=self.g_kind, command=self._auto_switch).grid(row=0, column=1, sticky="w")
        ttk.Label(self.g_frame, text="Start colour").grid(row=1, column=0, sticky="w", pady=4)
        self.g_start = ColorButton(self.g_frame, (255, 0, 0))
        self.g_start.grid(row=1, column=1, sticky="w")
        ttk.Label(self.g_frame, text="End colour").grid(row=1, column=2, sticky="w", padx=(12, 0))
        self.g_end = ColorButton(self.g_frame, (0, 0, 255))
        self.g_end.grid(row=1, column=3, sticky="w")
        self.g_angle_lbl = ttk.Label(self.g_frame, text="Angle ° (0 = left→right, 90 = top→bottom)")
        self.g_angle_lbl.grid(row=2, column=0, columnspan=3, sticky="w")
        self.g_angle = tk.StringVar(value="0")
        self.g_angle_sb = ttk.Spinbox(self.g_frame, from_=-360, to=360, width=6, textvariable=self.g_angle)
        self.g_angle_sb.grid(row=2, column=3, sticky="w")
        self.g_cx, self.g_cy = tk.StringVar(value="50"), tk.StringVar(value="50")
        self.g_center_lbl = ttk.Label(self.g_frame, text="Centre X% / Y%")
        self.g_center_lbl.grid(row=3, column=0, columnspan=2, sticky="w")
        cf = ttk.Frame(self.g_frame)
        cf.grid(row=3, column=2, columnspan=2, sticky="w")
        ttk.Spinbox(cf, from_=0, to=100, width=5, textvariable=self.g_cx).pack(side="left")
        ttk.Spinbox(cf, from_=0, to=100, width=5, textvariable=self.g_cy).pack(side="left", padx=4)
        self.g_center_frame = cf
        ttk.Label(self.g_frame, text="Match threshold (ΔE)").grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.g_delta = tk.StringVar(value="35")
        ttk.Spinbox(self.g_frame, from_=5, to=100, width=6, textvariable=self.g_delta).grid(row=4, column=3, sticky="w", pady=(6, 0))

        # scheme options
        self.s_frame = ttk.LabelFrame(self.opts, text="Colour scheme", padding=8)
        ttk.Label(self.s_frame, text="Type").grid(row=0, column=0, sticky="w")
        self.s_type = tk.StringVar(value=SCHEME_LABELS[colors.ANY_SCHEME])
        cb = ttk.Combobox(self.s_frame, textvariable=self.s_type, values=list(SCHEME_LABELS.values()), state="readonly", width=20)
        cb.grid(row=0, column=1, sticky="w", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._auto_switch())
        ttk.Label(self.s_frame, text="Base colour(s)").grid(row=1, column=0, sticky="w", pady=6)
        self.base_row = ttk.Frame(self.s_frame)
        self.base_row.grid(row=1, column=1, sticky="w", padx=6)
        self.base_btns: list[ColorButton] = []
        self.add_base_btn = ttk.Button(self.s_frame, text="+", width=3, command=self._add_base)
        self.add_base_btn.grid(row=1, column=2)
        self.rm_base_btn = ttk.Button(self.s_frame, text="−", width=3, command=self._rm_base)
        self.rm_base_btn.grid(row=1, column=3, padx=2)
        ttk.Label(self.s_frame, text="Hue tolerance °").grid(row=2, column=0, sticky="w")
        self.s_tol = tk.StringVar(value="30")
        ttk.Spinbox(self.s_frame, from_=1, to=90, width=6, textvariable=self.s_tol).grid(row=2, column=1, sticky="w", padx=6)
        self._add_base()

        sf = ttk.Frame(f)
        sf.pack(fill="x")
        ttk.Label(sf, text="Seed (optional)").pack(side="left")
        self.seed = tk.StringVar()
        ttk.Entry(sf, textvariable=self.seed, width=10).pack(side="left", padx=6)

        self.hint = tk.StringVar()
        ttk.Label(f, textvariable=self.hint, foreground="#a33", wraplength=700).pack(anchor="w", pady=6)
        self.suggest_btn = ttk.Button(f, text="Generate suggested colours", command=self._suggest)
        self.suggest_btn.pack(anchor="w", pady=(6, 2))
        Tooltip(self.suggest_btn, "Recommended for small image sets")
        self.confirm_btn = ttk.Button(f, text="Confirm", command=self._confirm)
        self.confirm_btn.pack(anchor="w", pady=2)
        self._auto_switch()
        return f

    def _add_base(self) -> None:
        if len(self.base_btns) < 3:
            b = ColorButton(self.base_row, (255, 0, 0))
            b.pack(side="left", padx=2)
            self.base_btns.append(b)

    def _rm_base(self) -> None:
        if len(self.base_btns) > 1:
            self.base_btns.pop().destroy()

    def _auto_switch(self) -> None:
        self.g_frame.pack_forget()
        self.s_frame.pack_forget()
        m = self.amode.get()
        if m == "gradient":
            self.g_frame.pack(fill="x")
            lin = self.g_kind.get() == "linear"
            self.g_angle_lbl.grid() if lin else self.g_angle_lbl.grid_remove()
            self.g_angle_sb.grid() if lin else self.g_angle_sb.grid_remove()
            self.g_center_lbl.grid_remove() if lin else self.g_center_lbl.grid()
            self.g_center_frame.grid_remove() if lin else self.g_center_frame.grid()
        elif m == "scheme":
            self.s_frame.pack(fill="x")
            any_ = LABEL_TO_SCHEME[self.s_type.get()] == colors.ANY_SCHEME
            st = "disabled" if any_ else "normal"
            for b in self.base_btns:
                b.configure(state=st)
            self.add_base_btn.configure(state=st)
            self.rm_base_btn.configure(state=st)
        self.suggest_btn.configure(state="disabled" if m == "random" else "normal")

    # ---------- auto: params <-> widgets
    def _num(self, var: tk.StringVar, default: float) -> float:
        try:
            return float(var.get())
        except ValueError:
            return default

    def _params(self) -> assign.AutoParams:
        seed = self.seed.get().strip()
        p = assign.AutoParams(mode=self.amode.get(), seed=int(seed) if seed.lstrip("-").isdigit() else None)
        p.gradient_kind = self.g_kind.get()
        p.angle = self._num(self.g_angle, 0.0)
        p.center = (self._num(self.g_cx, 50) / 100.0, self._num(self.g_cy, 50) / 100.0)
        p.start, p.end = self.g_start.rgb, self.g_end.rgb
        p.max_delta = self._num(self.g_delta, 35.0)
        p.scheme = LABEL_TO_SCHEME[self.s_type.get()]
        p.bases = [b.rgb for b in self.base_btns]
        p.tolerance = self._num(self.s_tol, 30.0)
        return p

    def _apply(self, p: assign.AutoParams) -> None:
        self.g_start.set(p.start)
        self.g_end.set(p.end)
        self.s_type.set(SCHEME_LABELS[p.scheme])
        while len(self.base_btns) < len(p.bases):
            self._add_base()
        while len(self.base_btns) > max(1, len(p.bases)):
            self._rm_base()
        for b, rgb in zip(self.base_btns, p.bases):
            b.set(rgb)
        self._auto_switch()

    # ---------- auto: actions
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        st = "disabled" if busy else "normal"
        self.confirm_btn.configure(state=st)
        if not busy:
            self._auto_switch()
        else:
            self.suggest_btn.configure(state="disabled")
        if not busy:
            self.progress.set(0)
            self.progress_text.set("")

    def _with_pools(self, then) -> None:
        self._set_busy(True)
        run_bg(
            self,
            lambda report: load_pools(self.folders, self.tags, self.cache, report),
            lambda res, err: self._pools_ready(res, err, then),
            self.progress,
            self.progress_text,
        )

    def _pools_ready(self, pools, err, then) -> None:
        self._set_busy(False)
        if err:
            messagebox.showerror("Error", str(err), parent=self)
            return
        then(pools)

    def _suggest(self) -> None:
        def go(pools):
            self._apply(assign.suggest(self.lt, pools, self._params()))
            self.hint.set("Suggested colours applied.")

        self._with_pools(go)

    def _confirm(self) -> None:
        p = self._params()
        if p.mode == "scheme" and p.scheme != colors.ANY_SCHEME and not p.bases:
            messagebox.showinfo("Colour scheme", "Pick a base colour or generate suggestions.", parent=self)
            return

        def go(pools):
            try:
                out = assign.auto_assign(self.lt, pools, p)
            except assign.PoolTooSmall as e:
                messagebox.showerror("Not enough images", str(e), parent=self)
                return
            except assign.NoFit as e:
                self._no_fit(pools, p, e)
                return
            self.on_done(out)

        self._with_pools(go)

    def _no_fit(self, pools, p: assign.AutoParams, err: assign.NoFit) -> None:
        if not self._warned:
            self._warned = True
            messagebox.showwarning(
                "No matching images",
                f"{err}\n\nSuggested colours will be generated for your image set.",
                parent=self,
            )
            self._apply(assign.suggest(self.lt, pools, p))
            self.hint.set("No images fit your settings; suggested colours were applied. Confirm again to retry.")
            return
        if messagebox.askyesno(
            "Still no exact match",
            f"{err}\n\nUse the closest matches anyway?",
            parent=self,
        ):
            relaxed = self._params()
            relaxed.strict = False
            try:
                self.on_done(assign.auto_assign(self.lt, pools, relaxed))
            except assign.PoolTooSmall as e:
                messagebox.showerror("Not enough images", str(e), parent=self)
