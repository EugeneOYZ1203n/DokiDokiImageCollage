"""Application flow: saved templates (pick / create) -> image folders -> size check -> select -> crop -> save."""
from __future__ import annotations

import logging
import os
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .. import instagram
from ..imageio import list_images
from ..models import LabelledTemplate, list_labelled, load_labelled, save_labelled, unique_path
from ..storage import Store, norm
from .cropper import CropperFrame
from .editor import TemplateEditor
from .common import tag_color
from .selector import SelectionFrame
from .settings import SettingsDialog

IMG_TYPES = [("Images", "*.png *.jpg *.jpeg"), ("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg")]
DEFAULT_GEOMETRY = "1200x780"


PREVIEW = 560


def draw_template_preview(canvas: tk.Canvas, lt: LabelledTemplate, size: int, highlight: str | None = None,
                          labels: bool = False):
    """Draw the template scaled into a size x size canvas; returns the PhotoImage (caller must keep it).

    labels=True: placeholders are coloured per tag and show the tag name; `highlight` emphasises one tag.
    """
    canvas.delete("all")
    img = Image.open(lt.template_path).convert("RGB")
    s = min(size / img.width, size / img.height)
    img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))))
    photo = ImageTk.PhotoImage(img)
    canvas.create_image(size / 2, size / 2, image=photo)
    ox, oy = (size - img.width) / 2, (size - img.height) / 2
    for ph in lt.placeholders:
        x0, y0 = ox + ph.x * s, oy + ph.y * s
        x1, y1 = ox + (ph.x + ph.w) * s, oy + (ph.y + ph.h) * s
        if not labels:
            canvas.create_rectangle(x0, y0, x1, y1, outline="#ffcc00", width=2)
            continue
        col = tag_color(lt, ph.tag)
        active = highlight is not None and ph.tag == highlight
        if active:
            canvas.create_rectangle(x0, y0, x1, y1, outline=col, width=4, fill=col, stipple="gray50")
        else:
            canvas.create_rectangle(x0, y0, x1, y1, outline=col, width=2 if highlight is None else 1)
        canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=ph.tag,
                           fill="white" if active or highlight is None else "#cccccc",
                           font=("", 11 if active else 9, "bold"), width=max(20, x1 - x0 - 6))
    return photo


class FolderWizard(ttk.Frame):
    """One step per tag: the preview highlights that tag's placeholders; the user picks its image folder."""

    def __init__(self, master, store: Store, lt: LabelledTemplate, on_done, on_back):
        super().__init__(master, padding=20)
        self.store, self.lt, self.on_done, self.on_back = store, lt, on_done, on_back
        self.order = lt.tags_used()
        self.choice: dict[str, str] = {}
        self.idx = 0
        self.folders: list[str] = []
        self._photo = None
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=PREVIEW, height=PREVIEW, background="#2b2b2b", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="n", padx=(0, 16))
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        self.header = ttk.Label(right, font=("", 13, "bold"))
        self.header.pack(anchor="w")
        self.sub = ttk.Label(right)
        self.sub.pack(anchor="w", pady=(2, 8))
        ttk.Label(right, text="Recent folders (or Browse for a new one):").pack(anchor="w")
        self.lb = tk.Listbox(right, selectmode="browse", exportselection=False)
        self.lb.pack(fill="both", expand=True, pady=6)
        self.lb.bind("<Double-Button-1>", lambda _e: self._next())
        row = ttk.Frame(right)
        row.pack(fill="x")
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left")
        ttk.Button(row, text="Forget selected", command=self._forget).pack(side="left", padx=6)
        nav = ttk.Frame(right)
        nav.pack(fill="x", pady=(12, 0))
        ttk.Button(nav, text="← Back", command=self._back).pack(side="left")
        self.next_btn = ttk.Button(nav, command=self._next)
        self.next_btn.pack(side="right")
        self._show_step()

    @property
    def tag(self) -> str:
        return self.order[self.idx]

    def _show_step(self) -> None:
        n = len(self.lt.by_tag(self.tag))
        self.header.configure(text=f'Folder {self.idx + 1} of {len(self.order)}:  "{self.tag}"')
        self.sub.configure(text=f"{n} placeholder(s) use this tag (highlighted).")
        self.next_btn.configure(text="Finish" if self.idx == len(self.order) - 1 else "Next →")
        self._photo = draw_template_preview(self.canvas, self.lt, PREVIEW, highlight=self.tag, labels=True)
        self._fill(self.choice.get(self.tag))

    def _fill(self, select: str | None) -> None:
        self.folders = list(self.store.recent_folders)
        self.lb.delete(0, "end")
        for i, p in enumerate(self.folders):
            gone = "" if os.path.isdir(p) else "   [missing]"
            self.lb.insert("end", f"{os.path.basename(os.path.normpath(p))}   —   {p}{gone}")
            if select and norm(p) == norm(select):
                self.lb.selection_set(i)
                self.lb.see(i)

    def _current(self) -> str | None:
        s = self.lb.curselection()
        return self.folders[s[0]] if s else None

    def _browse(self) -> None:
        recent = self.store.recent_folders
        start = os.path.dirname(recent[0]) if recent and os.path.isdir(os.path.dirname(recent[0])) else None
        d = filedialog.askdirectory(parent=self, title=f'Image folder for "{self.tag}"', initialdir=start)
        if d:
            d = os.path.normpath(d)
            self.store.add_recent(d)
            self._fill(d)

    def _forget(self) -> None:
        p = self._current()
        if p:
            self.store.remove_recent(p)
            self._fill(None)

    def _back(self) -> None:
        if self.idx == 0:
            self.on_back()
            return
        self.idx -= 1
        self._show_step()

    def _next(self) -> None:
        p = self._current()
        if not p:
            messagebox.showinfo("Folder", f'Choose a folder for "{self.tag}".', parent=self)
            return
        if not os.path.isdir(p):
            messagebox.showerror("Folder", f"Folder no longer exists:\n{p}", parent=self)
            return
        self.choice[self.tag] = p
        if self.idx < len(self.order) - 1:
            self.idx += 1
            self._show_step()
            return
        for q in reversed([self.choice[t] for t in self.order]):  # first tag ends up most recent
            self.store.add_recent(q)
        self.on_done(dict(self.choice))


class TemplatePicker(ttk.Frame):
    """Existing labelled templates first; creating a new one is the secondary action."""

    def __init__(self, master, paths: list[str], on_use, on_edit, on_new, on_delete):
        super().__init__(master, padding=20)
        self.paths, self.on_use, self.on_edit, self.on_delete = paths, on_use, on_edit, on_delete
        self._photo = None
        title = "Labelled templates" if paths else "No labelled templates yet"
        ttk.Label(self, text=title, font=("", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.lb = tk.Listbox(self, width=36, exportselection=False)
        self.lb.grid(row=1, column=0, sticky="ns", pady=8)
        for p in paths:
            self.lb.insert("end", os.path.splitext(os.path.basename(p))[0])
        self.lb.bind("<<ListboxSelect>>", self._preview)
        self.lb.bind("<Double-Button-1>", lambda _e: self._use())
        self.canvas = tk.Canvas(self, width=420, height=420, background="#2b2b2b", highlightthickness=0)
        self.canvas.grid(row=1, column=1, padx=16, pady=8)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        row = ttk.Frame(self)
        row.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(row, text="Use selected", command=self._use).pack(side="left")
        ttk.Button(row, text="Edit selected", command=self._edit).pack(side="left", padx=6)
        ttk.Button(row, text="Delete selected", command=self._delete).pack(side="left")
        ttk.Button(row, text="Create new...", command=on_new).pack(side="right")
        if paths:
            self.lb.selection_set(0)
            self._preview()

    def _sel(self) -> str | None:
        s = self.lb.curselection()
        return self.paths[s[0]] if s else None

    def _preview(self, _e=None) -> None:
        p = self._sel()
        self.canvas.delete("all")
        if not p:
            return
        try:
            lt = load_labelled(p)
            self._photo = draw_template_preview(self.canvas, lt, 420)
        except Exception as e:  # noqa: BLE001
            self.canvas.create_text(210, 210, text=f"Cannot load:\n{e}", fill="white", width=400)

    def _use(self) -> None:
        p = self._sel()
        if p:
            self.on_use(p)

    def _edit(self) -> None:
        p = self._sel()
        if p:
            self.on_edit(p)

    def _delete(self) -> None:
        p = self._sel()
        if p:
            self.on_delete(p)


class App(tk.Tk):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.images: dict[str, str] = {}
        self.color_cache: dict = {}
        self.current: tk.Widget | None = None
        self.title("Photo Collage")
        self.report_callback_exception = self._on_exception
        s = store.settings
        try:
            self.geometry(s.window_geometry if s.remember_window and s.window_geometry else DEFAULT_GEOMETRY)
        except tk.TclError:
            self.geometry(DEFAULT_GEOMETRY)
        self.minsize(900, 600)
        self._build_menu()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self.show_templates)

    # ---------- plumbing
    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        file = tk.Menu(bar, tearoff=False)
        file.add_command(label="Templates", command=self.show_templates)
        file.add_command(label="Settings...", command=lambda: SettingsDialog(self, self.store))
        file.add_separator()
        file.add_command(label="Open data folder", command=lambda: os.startfile(self.store.root))
        file.add_command(label="Open log", command=self._open_log)
        file.add_separator()
        file.add_command(label="Exit", command=self._close)
        bar.add_cascade(label="File", menu=file)
        self.config(menu=bar)

    def _open_log(self) -> None:
        if os.path.exists(self.store.log_file):
            os.startfile(self.store.log_file)
        else:
            messagebox.showinfo("Log", "No log yet.", parent=self)

    def _close(self) -> None:
        s = self.store.settings
        if s.remember_window:
            s.window_geometry = self.geometry()
            self.store.save()
        self.destroy()

    def show(self, frame: tk.Widget) -> None:
        if self.current is not None:
            self.current.destroy()
        self.current = frame
        frame.pack(fill="both", expand=True)

    def _on_exception(self, exc, val, tb) -> None:
        """Never die silently: log the traceback and tell the user."""
        text = "".join(traceback.format_exception(exc, val, tb))
        logging.getLogger(__name__).error(text)
        try:
            messagebox.showerror(
                "Unexpected error",
                f"{exc.__name__}: {val}\n\nDetails were written to:\n{self.store.log_file}",
                parent=self,
            )
        except tk.TclError:
            pass

    def error(self, title: str, msg: str) -> None:
        messagebox.showerror(title, msg, parent=self)

    # ---------- step 1: saved templates
    def show_templates(self) -> None:
        paths = list_labelled(self.store.templates_dir)
        self.show(TemplatePicker(self, paths, self._picked_use, self._picked_edit, self._pick_new, self._picked_delete))

    def _load(self, path: str) -> LabelledTemplate | None:
        """Load a labelled template; if its image is gone, let the user point at it again."""
        try:
            lt = load_labelled(path)
        except Exception as e:  # noqa: BLE001
            self.error("Labelled template", f"Cannot load {path}:\n{e}")
            return None
        if not os.path.exists(lt.template_path):
            if not messagebox.askyesno(
                "Template image missing",
                f"{lt.template_path}\nwas not found. Locate the image now?",
                parent=self,
            ):
                return None
            new = filedialog.askopenfilename(parent=self, title="Locate template image", filetypes=IMG_TYPES)
            if not new:
                return None
            lt.template_path = new
            save_labelled(lt, path)  # copies it into storage
        return lt

    def _picked_use(self, path: str) -> None:
        lt = self._load(path)
        if lt:
            self.show_folders(lt, path, self.show_templates)

    def _picked_edit(self, path: str) -> None:
        lt = self._load(path)
        if lt:
            self.open_editor(lt, path)

    def _picked_delete(self, path: str) -> None:
        name = os.path.splitext(os.path.basename(path))[0]
        if not messagebox.askyesno("Delete template", f"Delete '{name}'?", parent=self):
            return
        try:
            img = load_labelled(path).template_path
        except Exception:  # noqa: BLE001
            img = None
        os.remove(path)
        if img and os.path.isfile(img) and norm(os.path.dirname(img)) == norm(self.store.templates_dir):
            still_used = False
            for other in list_labelled(self.store.templates_dir):
                try:
                    still_used |= norm(load_labelled(other).template_path) == norm(img)
                except Exception:  # noqa: BLE001
                    pass
            if not still_used:
                os.remove(img)
        self.show_templates()

    def _pick_new(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose template image", filetypes=IMG_TYPES)
        if path:
            self.new_template(path)

    def new_template(self, image_path: str) -> None:
        try:
            with Image.open(image_path) as im:
                size = im.size
        except Exception as e:  # noqa: BLE001
            return self.error("Template", f"Cannot open {image_path}:\n{e}")
        self.open_editor(LabelledTemplate(os.path.abspath(image_path), size, []), None)

    def editor_tags(self) -> list[str]:
        """Tags the user already created in saved templates (no built-ins)."""
        tags: list[str] = []
        for p in list_labelled(self.store.templates_dir):
            try:
                for t in load_labelled(p).tags_used():
                    if t not in tags:
                        tags.append(t)
            except Exception:  # noqa: BLE001
                pass
        return tags

    def open_editor(self, lt: LabelledTemplate, path: str | None) -> None:
        tags = self.editor_tags()
        for t in lt.tags_used():
            if t not in tags:
                tags.append(t)
        self.show(TemplateEditor(
            self, lt, tags, self.store.templates_dir,
            on_continue=lambda lt2, p: self.show_folders(lt2, p, lambda: self.open_editor(lt2, p)),
            on_back=self.show_templates,
            existing_path=path,
            default_padding=self.store.settings.default_padding,
        ))

    # ---------- step 2: image folders
    def show_folders(self, lt: LabelledTemplate, path: str, back) -> None:
        self.show(FolderWizard(
            self, self.store, lt,
            on_done=lambda images: self._folders_chosen(lt, path, images), on_back=back,
        ))

    def _folders_chosen(self, lt: LabelledTemplate, path: str, images: dict[str, str]) -> None:
        self.images = images
        self.template_ready(lt, path)

    # ---------- step 3: size check, then validation
    def template_ready(self, lt: LabelledTemplate, path: str) -> None:
        try:
            with Image.open(lt.template_path) as im:
                real = im.size
        except Exception as e:  # noqa: BLE001
            self.error("Template image", f"Cannot open {lt.template_path}:\n{e}")
            return self.show_templates()
        if real != tuple(lt.size):
            if messagebox.askyesno(
                "Template size changed",
                f"The labelled template was made for {lt.size[0]}×{lt.size[1]} but the image is now "
                f"{real[0]}×{real[1]}.\n\nScale the placeholders to fit?",
                parent=self,
            ):
                lt = lt.scaled(real)
                for p in lt.placeholders:
                    p.rect = tuple(float(round(v)) for v in p.rect)
                save_labelled(lt, path)
            else:
                return self.open_editor(lt, path)
        mode = self.store.settings.instagram_size_mode
        rep = instagram.check_size(*lt.size)
        if not rep.ok and mode != "never":
            nw, nh = rep.nearest_size
            if mode == "resize":
                ans = True
            else:
                ans = messagebox.askyesnocancel(
                    "Not an Instagram size",
                    f"Template is {lt.size[0]}×{lt.size[1]}.\n\n- " + "\n- ".join(rep.warnings)
                    + f"\n\nResize to {rep.nearest} ({nw}×{nh})?\n\nYes = resize template\nNo = continue anyway\nCancel = go back",
                    parent=self,
                )
            if ans is None:
                return self.open_editor(lt, path)
            if ans:
                try:
                    lt, path = self._resize_template(lt, path, rep.nearest_size)
                except Exception as e:  # noqa: BLE001
                    return self.error("Resize failed", str(e))

        missing = [t for t in lt.tags_used() if t not in self.images]
        if missing:
            self.error("Missing image folders", "No image folder for tag(s): " + ", ".join(missing))
            return self.open_editor(lt, path)
        short = []
        for t in lt.tags_used():
            have, need = len(list_images(self.images[t])), len(lt.by_tag(t))
            if have < need:
                short.append(f"{t}: {need} placeholder(s), {have} image(s) in {self.images[t]}")
        if short:
            self.error("Not enough images", "Add images or remove placeholders:\n\n" + "\n".join(short))
            return self.open_editor(lt, path)
        self.show_selection(lt, path)

    def _resize_template(self, lt: LabelledTemplate, path: str, size) -> tuple[LabelledTemplate, str]:
        d = self.store.templates_dir
        os.makedirs(d, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        img_path = os.path.abspath(unique_path(d, f"{stem}_{size[0]}x{size[1]}", ".png"))
        instagram.resize_template_image(lt.template_path, size, img_path)
        new = lt.scaled(size, img_path)
        for p in new.placeholders:
            p.rect = tuple(float(round(v)) for v in p.rect)
        new_json = unique_path(d, f"{stem}_{size[0]}x{size[1]}")
        save_labelled(new, new_json)
        return new, new_json

    # ---------- selection + crop
    def show_selection(self, lt: LabelledTemplate, path: str) -> None:
        self.show(SelectionFrame(
            self, lt, self.images, self.color_cache,
            on_done=lambda a: self.show_cropper(lt, path, a),
            on_back=lambda: self.open_editor(lt, path),
        ))

    def show_cropper(self, lt: LabelledTemplate, path: str, assignments: dict[int, str]) -> None:
        name = os.path.splitext(os.path.basename(path))[0]
        self.show(CropperFrame(
            self, lt, assignments, self.store.settings.crop_tolerance, self.store.save_dialog_dir(),
            on_back=lambda: self.show_selection(lt, path), name=name, on_saved=self.store.note_saved,
        ))
