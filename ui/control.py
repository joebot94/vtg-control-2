"""CONTROL page: power, resolution, pattern, color, IRE, plus readouts.

Buttons highlight what the VTG is believed to be doing: set immediately on
click, then corrected by the periodic status poll.
"""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future
from tkinter import ttk
from typing import Callable

from vtg.protocol import (COLORS, DEFAULT_IRE_STEP, IRE_STEP_CHOICES, MAIN_PATTERNS, MORE_PATTERNS,
                          RESOLUTIONS, ire_steps, pattern_uses_ire)

from . import settings, theme

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


class ControlPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.state_vals = {"resolution": None, "pattern": None, "color": None,
                           "ire": None, "power": None, "temp": None}
        self._make_styles()
        app.on_theme_change(self._make_styles)

        # ---- readout ----
        top = ttk.Frame(self, style="Panel.TFrame", padding=(14, 8))
        top.pack(fill="x")
        self.refresh_btn = ttk.Button(top, text="Read VTG", command=self.refresh_all)
        self.refresh_btn.pack(side="right", anchor="n")
        self.res_lbl = ttk.Label(top, text="—", style="Big.TLabel")
        self.res_lbl.pack(anchor="w")
        self.detail_lbl = ttk.Label(top, text="", style="PanelDim.TLabel", font=app.fonts["mono"])
        self.detail_lbl.pack(anchor="w")

        def section(title: str) -> ttk.LabelFrame:
            f = ttk.LabelFrame(self, text=title, padding=(8, 6))
            f.pack(fill="x", pady=(8, 0))
            return f

        # Top to bottom = most to least used, like the original app.
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        f = ttk.LabelFrame(row, text="POWER", padding=(8, 6))
        f.pack(side="left", fill="both", expand=True, padx=(0, 4))
        power_styles = {"ON": ("PowerOn.TButton", "PowerOnSel.TButton"),
                        "OFF": ("PowerOff.TButton", "PowerOffSel.TButton")}
        self.power_group = ButtonGroup(f, ["ON", "OFF"], self.set_power, 2, styles=power_styles, width=6)
        self.power_group.pack(fill="x")
        f = ttk.LabelFrame(row, text="UNIT", padding=(8, 6))
        f.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.temp_lbl = ttk.Label(f, text="Temperature  —", style="Mono.TLabel")
        self.temp_lbl.pack(anchor="w", pady=4)

        f = section("IRE")
        self.ire_frame = f
        step = settings.load().get("ire_step", DEFAULT_IRE_STEP)
        self.ire_step = step if step in IRE_STEP_CHOICES else DEFAULT_IRE_STEP
        self.ire_group: ButtonGroup | None = None
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", side="bottom", pady=(6, 0))
        self.step_var = tk.StringVar(value=str(self.ire_step))
        step_box = ttk.Combobox(row, textvariable=self.step_var, width=3, state="readonly",
                                values=[str(v) for v in IRE_STEP_CHOICES])
        step_box.pack(side="right")
        step_box.bind("<<ComboboxSelected>>", lambda e: self.set_ire_step(int(self.step_var.get())))
        ttk.Label(row, text="Step", style="PanelDim.TLabel").pack(side="right", padx=(0, 6))
        self._build_ire_buttons()
        ttk.Label(row, text="Exact", style="PanelDim.TLabel").pack(side="left")
        self.ire_var = tk.StringVar(value="50")
        self.ire_spin = ttk.Spinbox(row, from_=0, to=100, textvariable=self.ire_var, width=5)
        self.ire_spin.pack(side="left", padx=6)
        self.ire_spin.bind("<Return>", lambda e: self._set_exact_ire())
        ttk.Button(row, text="Set", command=self._set_exact_ire).pack(side="left")

        f = section("PATTERN")
        self.pat_group = ButtonGroup(f, MAIN_PATTERNS, self.set_pattern, 3)
        self.pat_group.pack(fill="x")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="More", style="PanelDim.TLabel").pack(side="left")
        self.more_var = tk.StringVar()
        self.more_box = ttk.Combobox(row, textvariable=self.more_var, values=MORE_PATTERNS,
                                     state="readonly")
        self.more_box.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.more_box.bind("<<ComboboxSelected>>", lambda e: self.set_pattern(self.more_var.get()))

        f = section("COLOR")
        styles = {n: (f"Sw{n}.TButton", f"Sw{n}On.TButton") for n in COLORS}
        self.color_group = ButtonGroup(f, list(COLORS), self.set_color, 4, styles=styles, width=8)
        self.color_group.pack(fill="x")

        f = section("RESOLUTION")
        self.res_group = ButtonGroup(f, list(RESOLUTIONS), self.set_resolution, 4, width=8)
        self.res_group.pack(fill="x")

        app.on_state_change(self._on_connection)
        self._on_connection()

    def _build_ire_buttons(self) -> None:
        if self.ire_group is not None:
            self.ire_group.destroy()
        values = ire_steps(self.ire_step)
        cols = 7 if len(values) > 12 else min(6, len(values))
        self.ire_group = ButtonGroup(self.ire_frame, values, self.set_ire, cols, width=4)
        self.ire_group.pack(fill="x", side="top")

    def set_ire_step(self, step: int) -> None:
        """Rebuild the IRE buttons at a new step (5/10/20/25) and remember it."""
        if step not in IRE_STEP_CHOICES or step == self.ire_step:
            return
        self.ire_step = step
        self.step_var.set(str(step))
        self._build_ire_buttons()
        self._render()
        settings.save(ire_step=step)

    def build_footer(self) -> None:
        """Enable HCFR + Toggle Theme, as in the original app. Called once all pages exist."""
        row = ttk.Frame(self)
        row.pack(fill="x", side="bottom", pady=(10, 0))
        self.app.hcfr.add_toggle(row).pack(side="left")
        ttk.Button(row, text="Toggle Theme", command=self.app.toggle_theme).pack(side="right")

    def _make_styles(self) -> None:
        s = ttk.Style()
        for name, col in (("PowerOn", theme.POWER_ON), ("PowerOff", theme.POWER_OFF)):
            s.configure(f"{name}.TButton", background=col, foreground="#ffffff")
            s.map(f"{name}.TButton", background=[("active", col), ("pressed", col)])
            s.configure(f"{name}Sel.TButton", background=col, foreground="#ffffff",
                        font=self.app.fonts["ui_bold"])
            s.map(f"{name}Sel.TButton", background=[("active", col), ("pressed", col)])
        for name, hexcol in SWATCHES.items():
            fg = "#000000" if name in DARK_TEXT else "#ffffff"
            s.configure(f"Sw{name}.TButton", background=hexcol, foreground=fg,
                        bordercolor=theme.LINE, lightcolor=hexcol, darkcolor=hexcol,
                        relief="solid", borderwidth=1)
            s.map(f"Sw{name}.TButton", background=[("active", hexcol), ("pressed", hexcol)])
            s.configure(f"Sw{name}On.TButton", background=hexcol, foreground=fg,
                        bordercolor=theme.ACCENT, lightcolor=hexcol,
                        darkcolor=hexcol, relief="solid", borderwidth=2,
                        font=self.app.fonts["ui_bold"])
            s.map(f"Sw{name}On.TButton", background=[("active", hexcol), ("pressed", hexcol)])

    # ------------------------------------------------------------ state --
    def _on_connection(self) -> None:
        # Buttons stay lit while disconnected (clicking says "Not connected").
        if self.app.session is None:
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
            f"PAT {(v['pattern'] or '—')[:16]}",
            f"COL {v['color'] or '—'}",
            f"IRE {'—' if v['ire'] is None else v['ire']}",
            f"PWR {v['power'] or '—'}",
        ]
        self.detail_lbl.configure(text="  ".join(parts))
        self.res_group.select(v["resolution"])
        self.pat_group.select(v["pattern"])
        self.more_var.set(v["pattern"] if v["pattern"] in MORE_PATTERNS else "")
        ire_note = "" if v["pattern"] is None or pattern_uses_ire(v["pattern"]) else \
            "  (not used by this pattern)"
        self.ire_frame.configure(text="IRE" + ire_note)
        self.color_group.select(v["color"])
        self.power_group.select(v["power"])
        ire = v["ire"]
        nearest = None if ire is None else min(ire_steps(self.ire_step), key=lambda k: abs(k - ire))
        self.ire_group.select(nearest)
        t = v["temp"]
        self.temp_lbl.configure(text=f"Temperature  {'—' if t is None else f'{t:.0f} °F'}")

    # ----------------------------------------------------------- actions --
    @property
    def vtg(self):
        return self.app.session.vtg if self.app.session else None

    def _need_vtg(self):
        """The protocol for a button press, or None (and a status-bar hint)."""
        if self.vtg is None:
            self.app.notify("Not connected — pick a port (or MOCK) and Connect")
        return self.vtg

    def _do(self, fut: Future, **optimistic) -> None:
        self._update(**optimistic)

        def done(f: Future) -> None:
            if f.exception():
                self.refresh_all()  # we don't know what state it's in now
        self.app.when_done(fut, done)

    def set_resolution(self, name: str) -> None:
        if self._need_vtg():
            self._do(self.vtg.set_resolution(name), resolution=name)

    def set_pattern(self, name: str) -> None:
        if self._need_vtg():
            self._do(self.vtg.set_pattern(name), pattern=name)

    def set_color(self, name: str) -> None:
        if self._need_vtg():
            self._do(self.vtg.set_color(name), color=name)

    def set_ire(self, value: int) -> None:
        if self._need_vtg():
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
        if self._need_vtg():
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
        if not self._need_vtg():
            return
        self.refresh_from_device()
        self.refresh_temperature()
