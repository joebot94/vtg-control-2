"""TIMINGS page: manual custom-timing editor with live derived values."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from vtg import presets
from vtg.protocol import NotCaptured
from vtg.timing import ClockSource, Timing, TimingError, example_320x240

# clock source -> (label, display unit, Hz per display unit)
CLOCK_UNITS = {
    ClockSource.REFRESH: ("Refresh", "Hz", 1.0),
    ClockSource.H_FREQ: ("H freq", "kHz", 1e3),
    ClockSource.PIXEL_CLOCK: ("Pixel clock", "MHz", 1e6),
}
COLS = ("active", "front", "sync", "back")
H_KEYS = ("width", "h_front_porch", "h_sync_width", "h_back_porch")
V_KEYS = ("height", "v_front_porch", "v_sync_width", "v_back_porch")


class TimingsPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self._loading = False
        self._field_source = ClockSource.REFRESH  # units the clock field is in
        self.vars: dict[str, tk.StringVar] = {}
        mono = app.fonts["mono"]

        panel = ttk.LabelFrame(self, text="CUSTOM TIMING", padding=14)
        panel.pack(side="left", fill="y", anchor="n")

        # name
        row = ttk.Frame(panel, style="Panel.TFrame")
        row.grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, 10))
        ttk.Label(row, text="Name", style="PanelDim.TLabel", width=8).pack(side="left")
        self.vars["name"] = tk.StringVar()
        ttk.Entry(row, textvariable=self.vars["name"], width=34).pack(side="left", fill="x", expand=True)

        # clock source + value
        row = ttk.Frame(panel, style="Panel.TFrame")
        row.grid(row=1, column=0, columnspan=6, sticky="ew")
        ttk.Label(row, text="Clock", style="PanelDim.TLabel", width=8).pack(side="left")
        self.source_var = tk.StringVar(value=ClockSource.REFRESH.value)
        for src, (label, _unit, _scale) in CLOCK_UNITS.items():
            ttk.Radiobutton(row, text=label, value=src.value, variable=self.source_var,
                            command=self._on_source_change).pack(side="left", padx=(0, 8))
        row = ttk.Frame(panel, style="Panel.TFrame")
        row.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(4, 12))
        ttk.Label(row, text="", style="PanelDim.TLabel", width=8).pack(side="left")
        self.vars["clock"] = tk.StringVar()
        ttk.Entry(row, textvariable=self.vars["clock"], width=14, font=mono).pack(side="left")
        self.unit_lbl = ttk.Label(row, text="Hz", style="PanelDim.TLabel")
        self.unit_lbl.pack(side="left", padx=6)
        ttk.Label(row, text="← authoritative", style="PanelDim.TLabel").pack(side="left", padx=6)

        # porch grid
        for c, head in enumerate(("",) + tuple(h.upper() for h in COLS) + ("TOTAL",)):
            ttk.Label(panel, text=head, style="PanelDim.TLabel").grid(row=3, column=c, padx=4, sticky="e")
        self.total_lbls = {}
        for r, (axis, keys) in enumerate((("Horizontal", H_KEYS), ("Vertical", V_KEYS)), start=4):
            ttk.Label(panel, text=axis, style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=3)
            for c, key in enumerate(keys, start=1):
                self.vars[key] = tk.StringVar()
                ttk.Spinbox(panel, from_=0, to=9999, textvariable=self.vars[key], width=6,
                            font=mono, justify="right").grid(row=r, column=c, padx=4, pady=3)
            self.total_lbls[axis] = ttk.Label(panel, text="—", style="MonoAccent.TLabel", width=6,
                                              anchor="e")
            self.total_lbls[axis].grid(row=r, column=5, padx=4)

        # polarity / scan
        row = ttk.Frame(panel, style="Panel.TFrame")
        row.grid(row=6, column=0, columnspan=6, sticky="w", pady=(12, 0))
        for key, label in (("h_sync_polarity", "H sync"), ("v_sync_polarity", "V sync")):
            ttk.Label(row, text=label, style="PanelDim.TLabel").pack(side="left")
            self.vars[key] = tk.StringVar(value="-")
            ttk.Combobox(row, textvariable=self.vars[key], values=("+", "-"), width=2,
                         state="readonly").pack(side="left", padx=(4, 16))
        self.interlaced_var = tk.BooleanVar()
        ttk.Checkbutton(row, text="Interlaced", variable=self.interlaced_var,
                        command=self._recompute).pack(side="left")

        # buttons
        row = ttk.Frame(panel, style="Panel.TFrame")
        row.grid(row=7, column=0, columnspan=6, sticky="ew", pady=(18, 0))
        ttk.Button(row, text="Example", command=lambda: self.load_timing(example_320x240())
                   ).pack(side="left")
        ttk.Button(row, text="SAVE PRESET", command=self.save_preset).pack(side="left", padx=6)
        self.program_btn = ttk.Button(row, text="PROGRAM VTG", style="Accent.TButton",
                                      command=self.program)
        self.program_btn.pack(side="right")
        self.program_note = ttk.Label(panel, text="", style="PanelDim.TLabel", wraplength=420,
                                      justify="left")
        self.program_note.grid(row=8, column=0, columnspan=6, sticky="w", pady=(8, 0))

        # ---- derived readout ----
        out = ttk.LabelFrame(self, text="DERIVED", padding=14)
        out.pack(side="left", fill="both", expand=True, anchor="n", padx=(10, 0))
        self.res_lbl = ttk.Label(out, text="—", style="Big.TLabel")
        self.res_lbl.pack(anchor="w")
        self.derived = {}
        for key in ("Refresh", "H freq", "Pixel clock", "H total", "V total", "Blanking"):
            r = ttk.Frame(out, style="Panel.TFrame")
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=key, style="PanelDim.TLabel", width=12).pack(side="left")
            self.derived[key] = ttk.Label(r, text="—", style="Mid.TLabel")
            self.derived[key].pack(side="left")
        self.msg_lbl = ttk.Label(out, text="", style="Warn.TLabel", wraplength=300, justify="left")
        self.msg_lbl.pack(anchor="w", pady=(14, 0))

        for key, var in self.vars.items():
            var.trace_add("write", lambda *_: self._recompute())
        app.on_state_change(self._update_program_state)
        self.load_timing(example_320x240())

    # ------------------------------------------------------------ model --
    def _source(self) -> ClockSource:
        return ClockSource(self.source_var.get())

    def current_timing(self) -> Timing:
        """Build a Timing from the fields. Raises TimingError on bad input."""
        v = {k: var.get().strip() for k, var in self.vars.items()}
        ints = {}
        for key in H_KEYS + V_KEYS:
            try:
                ints[key] = int(v[key])
            except ValueError:
                raise TimingError(f"{key.replace('_', ' ')}: not a whole number") from None
        src = self._field_source
        try:
            clock = float(v["clock"]) * CLOCK_UNITS[src][2]
        except ValueError:
            raise TimingError("clock value: not a number") from None
        t = Timing(name=v["name"] or "Untitled", h_sync_polarity=v["h_sync_polarity"],
                   v_sync_polarity=v["v_sync_polarity"], interlaced=self.interlaced_var.get(),
                   clock_source=src, clock_value=clock, **ints)
        t.validate()
        return t

    def load_timing(self, t: Timing) -> None:
        self._loading = True
        try:
            self.vars["name"].set(t.name)
            for key in H_KEYS + V_KEYS:
                self.vars[key].set(str(getattr(t, key)))
            self.vars["h_sync_polarity"].set(t.h_sync_polarity)
            self.vars["v_sync_polarity"].set(t.v_sync_polarity)
            self.interlaced_var.set(t.interlaced)
            self.source_var.set(t.clock_source.value)
            self._set_clock_field(t.clock_source, t.clock_value)
        finally:
            self._loading = False
        self._recompute()

    def _set_clock_field(self, src: ClockSource, hz: float) -> None:
        _, unit, scale = CLOCK_UNITS[src]
        self._field_source = src
        self.unit_lbl.configure(text=unit)
        # 12 significant digits: switching sources back and forth doesn't drift
        self.vars["clock"].set(f"{hz / scale:.12g}")

    def _on_source_change(self) -> None:
        """Switch which figure is authoritative without changing the timing."""
        new = self._source()
        try:
            t = self.current_timing()
            self._set_clock_field(new, t.clock_for(new))
        except TimingError:
            self._field_source = new
            self.unit_lbl.configure(text=CLOCK_UNITS[new][1])
        self._recompute()

    def _recompute(self) -> None:
        if self._loading:
            return
        try:
            t = self.current_timing()
        except TimingError as exc:
            for lbl in self.derived.values():
                lbl.configure(text="—")
            for lbl in self.total_lbls.values():
                lbl.configure(text="—")
            self.res_lbl.configure(text="—")
            self.msg_lbl.configure(text=str(exc))
            return
        src = t.clock_source
        star = {s: ("  ◆" if s is src else "") for s in ClockSource}
        self.res_lbl.configure(text=f"{t.width} × {t.height}{'i' if t.interlaced else 'p'}")
        self.derived["Refresh"].configure(text=f"{t.refresh:.3f} Hz{star[ClockSource.REFRESH]}")
        self.derived["H freq"].configure(text=f"{t.h_freq / 1e3:.3f} kHz{star[ClockSource.H_FREQ]}")
        self.derived["Pixel clock"].configure(
            text=f"{t.pixel_clock / 1e6:.3f} MHz{star[ClockSource.PIXEL_CLOCK]}")
        self.derived["H total"].configure(text=str(t.h_total))
        self.derived["V total"].configure(text=str(t.v_total))
        self.derived["Blanking"].configure(text=f"H {t.h_blank}   V {t.v_blank}")
        self.total_lbls["Horizontal"].configure(text=str(t.h_total))
        self.total_lbls["Vertical"].configure(text=str(t.v_total))
        self.msg_lbl.configure(text="\n".join(t.warnings()))

    # ---------------------------------------------------------- actions --
    def save_preset(self) -> None:
        try:
            t = self.current_timing()
        except TimingError as exc:
            messagebox.showerror("Can't save", str(exc), parent=self)
            return
        path = presets.PRESET_DIR / f"{presets.slug(t.name)}.json"
        if path.exists() and not messagebox.askyesno(
                "Overwrite?", f"{path.name} exists. Overwrite it?", parent=self):
            return
        presets.save(t, path)
        self.app.log.info(f"saved preset {path.name}")
        self.app.presets.reload()

    def _update_program_state(self) -> None:
        s = self.app.session
        if s is None:
            reason = "Not connected."
        elif s.is_mock:
            reason = "MOCK transport — nothing to program."
        elif not s.vtg.supports_custom_timing:
            reason = ("Custom-timing upload protocol not captured yet. "
                      "Capture the official Extron software first.")
        else:
            reason = ""
        self.program_btn.state(["disabled"] if reason else ["!disabled"])
        self.program_note.configure(text=reason)

    def program(self) -> None:
        s = self.app.session
        if not s or s.is_mock:
            return
        try:
            fut = s.vtg.program_timing(self.current_timing())
        except (NotCaptured, TimingError) as exc:
            messagebox.showerror("Can't program", str(exc), parent=self)
            return
        self.app.when_done(fut, lambda f: self.app.log.info(
            f"program_timing -> {f.exception() or f.result()}"))
