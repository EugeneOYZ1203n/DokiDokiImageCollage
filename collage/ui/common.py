"""Shared Tk helpers."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import colorchooser, ttk

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324", "#800000"]


def tag_color(lt, tag: str) -> str:
    """One colour per tag, shared by the editor and the folder wizard preview."""
    try:
        return PALETTE[lt.tags_used().index(tag) % len(PALETTE)]
    except ValueError:
        return "#ffffff"


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, background="#ffffe0", relief="solid", borderwidth=1, padx=4, pady=2).pack()

    def _hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def hex_of(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


class ColorButton(tk.Button):
    """Button showing a colour; click opens the chooser."""

    def __init__(self, master, rgb=(128, 128, 128), command=None, **kw):
        super().__init__(master, width=4, relief="solid", command=self._pick, **kw)
        self._cmd = command
        self.set(rgb)

    @property
    def rgb(self) -> tuple[int, int, int]:
        return self._rgb

    def set(self, rgb) -> None:
        self._rgb = tuple(int(c) for c in rgb)
        self.configure(bg=hex_of(self._rgb), activebackground=hex_of(self._rgb))

    def _pick(self) -> None:
        res = colorchooser.askcolor(color=hex_of(self._rgb), parent=self)
        if res and res[0]:
            self.set(res[0])
            if self._cmd:
                self._cmd()


def run_bg(widget: tk.Misc, work, done, progress: tk.DoubleVar | None = None, label: tk.StringVar | None = None):
    """Run work(report) in a thread; call done(result, error) on the Tk thread.

    `report(fraction, text)` may be called from the worker.
    """
    q: queue.Queue = queue.Queue()
    state = {"frac": 0.0, "text": ""}

    def report(frac: float, text: str = "") -> None:
        state["frac"], state["text"] = frac, text

    def target():
        try:
            q.put((work(report), None))
        except Exception as e:  # noqa: BLE001
            q.put((None, e))

    def poll():
        if not widget.winfo_exists():
            return
        try:
            res, err = q.get_nowait()
        except queue.Empty:
            if progress is not None:
                progress.set(state["frac"] * 100)
            if label is not None:
                label.set(state["text"])
            widget.after(60, poll)
            return
        try:
            done(res, err)
        except tk.TclError:  # widget destroyed while work was running
            pass

    threading.Thread(target=target, daemon=True).start()
    widget.after(60, poll)


class BusyOverlay(ttk.Frame):
    """Progress bar page shown while background work runs."""

    def __init__(self, master, text: str = "Working..."):
        super().__init__(master, padding=40)
        ttk.Label(self, text=text, font=("", 12)).pack(pady=(60, 10))
        self.progress = tk.DoubleVar(value=0)
        self.label = tk.StringVar()
        ttk.Progressbar(self, variable=self.progress, maximum=100, length=360).pack(pady=6)
        ttk.Label(self, textvariable=self.label).pack()
