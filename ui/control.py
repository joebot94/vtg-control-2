"""CONTROL page: power, resolution, pattern, color, IRE, plus readouts.

Buttons highlight what the VTG is believed to be doing: set immediately on
click, then corrected by the periodic status poll.
"""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future
from tkinter import ttk
from typing import Callable

from vtg.protocol import COLORS, IRE_STEPS, PATTERNS, RESOLUTIONS

from . import theme

SWATCHES = {
    "Black": "#000000", "Blue": "#1f3cff", "Green": "#1fd11f", "Cyan": "#1fd6de",
    "Red": "#f01e1e", "Magenta": "#e81ee8", "Yellow": "#f2e21a", "White": "#f2f2f2",
}
DARK_TEXT = {"Green", "Cyan", "Yellow", "White"}


class ButtonGroup(ttk.Frame):
    """Grid of buttons where one can be marked as the current selection."""

    def __init__(self, master, names, command: Callable[[str], None], columns: int,
                 styles: dict[str, tuple[str, str]] | None = None, width: int = 10):
        super().__init__(master, style="Panel.TFrame")
        self._buttons: dict[str, ttk.Button] = {}
        # name -> (normal style, selected style)
        self._styles = styles or {}
        for i, name in enumerate(names):
            b = ttk.Button(self, text=str(name), width=width,
                           style=self._styles.get(name, ("TButton", ""))[0],
                           command=lambda n=name: command(n))
            b.grid(row=i // columns, column=i % columns, padx=2, pady=2, sticky="ew")
            self._buttons[name] = b
        for c in range(columns):
            self.columnconfigure(c, weight=1)

    def select(self, chosen) -> None:
        for name, b in self._buttons.items():
            normal, selected = self._styles.get(name, ("TButton", "On.TButton"))
            on = name == chosen
            b.configure(style=selected if on else normal)
            if name in self._styles:  # swatches: colour can't show selection, text can
                b.configure(text=f"● {name}" if on else str(name))

    def set_enabled(self, enabled: bool) -> None:
        for b in self._buttons.values():
            b.state(["!disabled"] if enabled else ["disabled"])


class ControlPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.state_vals = {"resolution": None, "pattern": None, "color": None,
                           "ire": None, "power": None, "temp": None}
        self._make_swatch_styles()

        # ---- readout ----
        top = ttk.Frame(self, style="Panel.TFrame", padding=(14, 8))
        top.pack(fill="x")
        self.refresh_btn = ttk.Button(top, text="Read VTG", command=self.refresh_all)
        self.refresh_btn.pack(side="right", anchor="n")
        self.res_lbl = ttk.Label(top, text="—", style="Big.TLabel")
        self.res_lbl.pack(anchor="w")
        self.detail_lbl = ttk.Label(top, text="", style="PanelDim.TLabel", font=app.fonts["mono"])
        self.detail_lbl.pack(anchor="w")

        def section(title: str, pady=(8, 0)) -> ttk.LabelFrame:
            f = ttk.LabelFrame(self, text=title, padding=(8, 6))
            f.pack(fill="x", pady=pady)
            return f

        # OUTPUT and UNIT share a row
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        f = ttk.LabelFrame(row, text="OUTPUT", padding=(8, 6))
        f.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.power_group = ButtonGroup(f, ["ON", "OFF"], self.set_power, 2, width=6)
        self.power_group.pack(fill="x")
        f = ttk.LabelFrame(row, text="UNIT", padding=(8, 6))
        f.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.temp_lbl = ttk.Label(f, text="Temperature  —", style="Mono.TLabel")
        self.temp_lbl.pack(anchor="w", pady=4)

        f = section("RESOLUTION")
        self.res_group = ButtonGroup(f, list(RESOLUTIONS), self.set_resolution, 4, width=8)
        self.res_group.pack(fill="x")

        f = section("PATTERN")
        self.pat_group = ButtonGroup(f, list(PATTERNS), self.set_pattern, 3)
        self.pat_group.pack(fill="x")

        f = section("COLOR")
        styles = {n: (f"Sw{n}.TButton", f"Sw{n}On.TButton") for n in COLORS}
        self.color_group = ButtonGroup(f, list(COLORS), self.set_color, 4, styles=styles, width=8)
        self.color_group.pack(fill="x")

        f = section("IRE")
        self.ire_group = ButtonGroup(f, IRE_STEPS, self.set_ire, 6, width=4)
        self.ire_group.pack(fill="x")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Exact", style="PanelDim.TLabel").pack(side="left")
        self.ire_var = tk.StringVar(value="50")
        self.ire_spin = ttk.Spinbox(row, from_=0, to=100, textvariable=self.ire_var, width=5)
        self.ire_spin.pack(side="left", padx=6)
        self.ire_spin.bind("<Return>", lambda e: self._set_exact_ire())
        self.ire_set_btn = ttk.Button(row, text="Set", command=self._set_exact_ire)
        self.ire_set_btn.pack(side="left")

        self.groups = [self.res_group, self.pat_group, self.power_group,
                       self.color_group, self.ire_group]
        app.on_state_change(self._on_connection)
        self._on_connection()

    def _make_swatch_styles(self) -> None:
        s = ttk.Style()
        for name, hexcol in SWATCHES.items():
            fg = "#000000" if name in DARK_TEXT else "#ffffff"
            s.configure(f"Sw{name}.TButton", background=hexcol, foreground=fg,
                        bordercolor=theme.LINE, borderwidth=1)
            s.map(f"Sw{name}.TButton", background=[("disabled", theme.PANEL)],
                  foreground=[("disabled", theme.FG_DIM)])
            s.configure(f"Sw{name}On.TButton", background=hexcol, foreground=fg,
                        bordercolor=theme.ACCENT, lightcolor=theme.ACCENT,
                        darkcolor=theme.ACCENT, borderwidth=3,
                        font=self.app.fonts["ui_bold"])

    # ------------------------------------------------------------ state --
    def _on_connection(self) -> None:
        on = self.app.session is not None
        for g in self.groups:
            g.set_enabled(on)
        for w in (self.ire_spin, self.ire_set_btn, self.refresh_btn):
            w.state(["!disabled"] if on else ["disabled"])
        if not on:
            for k in self.state_vals:
                self.state_vals[k] = None
        self._render()

    def _update(self, **kw) -> None:
        self.state_vals.update(kw)
        self._render()

    def _render(self) -> None:
        v = self.state_vals
        self.res_lbl.configure(text=v["resolution"] or "—")
        parts = [
            f"PAT {v['pattern'] or '—'}",
            f"COL {v['color'] or '—'}",
            f"IRE {'—' if v['ire'] is None else v['ire']}",
            f"OUT {v['power'] or '—'}",
        ]
        self.detail_lbl.configure(text="  ".join(parts))
        self.res_group.select(v["resolution"])
        self.pat_group.select(v["pattern"])
        self.color_group.select(v["color"])
        self.power_group.select(v["power"])
        ire = v["ire"]
        nearest = None if ire is None else min(IRE_STEPS, key=lambda k: abs(k - ire))
        self.ire_group.select(nearest)
        t = v["temp"]
        self.temp_lbl.configure(text=f"Temperature  {'—' if t is None else f'{t:.0f} °F'}")

    # ----------------------------------------------------------- actions --
    @property
    def vtg(self):
        return self.app.session.vtg if self.app.session else None

    def _do(self, fut: Future, **optimistic) -> None:
        self._update(**optimistic)

        def done(f: Future) -> None:
            if f.exception():
                self.refresh_all()  # we don't know what state it's in now
        self.app.when_done(fut, done)

    def set_resolution(self, name: str) -> None:
        if self.vtg:
            self._do(self.vtg.set_resolution(name), resolution=name)

    def set_pattern(self, name: str) -> None:
        if self.vtg:
            self._do(self.vtg.set_pattern(name), pattern=name)

    def set_color(self, name: str) -> None:
        if self.vtg:
            self._do(self.vtg.set_color(name), color=name)

    def set_ire(self, value: int) -> None:
        if self.vtg:
            self.ire_var.set(str(value))
            self._do(self.vtg.set_ire(int(value)), ire=int(value))

    def _set_exact_ire(self) -> None:
        try:
            v = int(self.ire_var.get())
        except ValueError:
            return
        if 0 <= v <= 100:
            self.set_ire(v)

    def set_power(self, which: str) -> None:
        if self.vtg:
            self._do(self.vtg.set_power(which == "ON"), power=which)

    # ------------------------------------------------------------ polling --
    def _read(self, fut: Future, key: str) -> None:
        def done(f: Future) -> None:
            if not f.exception() and f.result() is not None:
                self._update(**{key: f.result()})
        self.app.when_done(fut, done)

    def refresh_from_device(self) -> None:
        if self.vtg:
            self._read(self.vtg.query_resolution(), "resolution")
            self._read(self.vtg.query_pattern(), "pattern")
            self._read(self.vtg.query_ire(), "ire")

    def refresh_temperature(self) -> None:
        if self.vtg:
            self._read(self.vtg.query_temperature(), "temp")

    def refresh_all(self) -> None:
        self.refresh_from_device()
        self.refresh_temperature()
