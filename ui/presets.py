"""PRESETS page: browse the presets/ folder, load one into the timing editor."""

from __future__ import annotations

import shutil
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vtg import presets
from vtg.timing import TimingError

COLUMNS = (("name", "Name", 150), ("res", "Res", 70), ("refresh", "Refresh", 75),
           ("hfreq", "H freq", 75), ("pclk", "Pixel clk", 80))


class PresetsPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self._paths: dict[str, Path] = {}

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="LOAD", style="Accent.TButton",
                   command=self.load_selected).pack(side="left")
        ttk.Button(bar, text="Import…", command=self.import_file).pack(side="left", padx=6)
        ttk.Button(bar, text="Refresh", command=self.reload).pack(side="left")

        self.tree = ttk.Treeview(self, columns=[c[0] for c in COLUMNS], show="headings",
                                 selectmode="browse")
        for key, head, width in COLUMNS:
            self.tree.heading(key, text=head, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=key == "name")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.load_selected())
        self.err_lbl = ttk.Label(self, text="", style="Dim.TLabel", wraplength=480)
        self.err_lbl.pack(anchor="w", pady=(6, 0))
        self.reload()

    def reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._paths.clear()
        bad = []
        for path in presets.list_presets():
            try:
                t = presets.load(path)
            except (TimingError, ValueError, KeyError) as exc:
                bad.append(f"{path.name}: {exc}")
                continue
            iid = self.tree.insert("", "end", values=(
                t.name, f"{t.width}×{t.height}{'i' if t.interlaced else 'p'}",
                f"{t.refresh:.3f}", f"{t.h_freq / 1e3:.3f}k",
                f"{t.pixel_clock / 1e6:.3f}M"))
            self._paths[iid] = path
        self.err_lbl.configure(text=("Skipped: " + "; ".join(bad)) if bad else
                               f"{len(self._paths)} preset(s) in {presets.PRESET_DIR}")

    def load_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        path = self._paths[sel[0]]
        self.app.timings.load_timing(presets.load(path))
        self.app.log.info(f"loaded preset {path.name}")
        self.app.notebook.select(self.app.timings)

    def import_file(self) -> None:
        src = filedialog.askopenfilename(parent=self, title="Import timing preset",
                                         filetypes=[("Timing preset", "*.json")])
        if not src:
            return
        try:
            presets.load(src)
        except (TimingError, ValueError, KeyError) as exc:
            messagebox.showerror("Not a valid preset", str(exc), parent=self)
            return
        dest = presets.PRESET_DIR / Path(src).name
        if dest.exists() and not messagebox.askyesno(
                "Overwrite?", f"{dest.name} exists. Overwrite it?", parent=self):
            return
        shutil.copyfile(src, dest)
        self.reload()
