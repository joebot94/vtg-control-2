"""HCFR page: follow HCFR's Information window (Windows), plus an offline tester."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vtg import hcfr

from . import theme


class HCFRPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.watcher = hcfr.HCFRWatcher(lambda d: app.call_soon(self._apply, d))

        box = ttk.LabelFrame(self, text="HCFR FOLLOW", padding=12)
        box.pack(fill="x")
        self.enable_var = tk.BooleanVar()
        self.enable_chk = ttk.Checkbutton(box, text="Follow HCFR's Information window",
                                          variable=self.enable_var, command=self._toggle)
        self.enable_chk.pack(anchor="w")
        self.status_lbl = ttk.Label(box, text="", style="PanelDim.TLabel")
        self.status_lbl.pack(anchor="w", pady=(6, 0))
        ttk.Label(box, text="Colour cues (Red Primary … Yellow Secondary, White) set the VTG colour; "
                            "“NN% Gray” sets IRE to the nearest 10. Only changes are sent.",
                  style="PanelDim.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(6, 0))

        box = ttk.LabelFrame(self, text="TEST — paste HCFR text", padding=12)
        box.pack(fill="both", expand=True, pady=(10, 0))
        self.test_text = tk.Text(box, height=6, bg=theme.PANEL_HI, fg=theme.FG,
                                 insertbackground=theme.FG, relief="flat", font=app.fonts["mono"],
                                 highlightthickness=0, padx=6, pady=4)
        self.test_text.pack(fill="x")
        self.test_text.bind("<KeyRelease>", lambda e: self._test())
        row = ttk.Frame(box, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Decision", style="PanelDim.TLabel").pack(side="left")
        self.test_lbl = ttk.Label(row, text="—", style="MonoAccent.TLabel")
        self.test_lbl.pack(side="left", padx=10)
        self.test_send = ttk.Button(row, text="Send it", command=self._send_test)
        self.test_send.pack(side="right")

        app.on_state_change(self._on_state)
        self._on_state()

    def _on_state(self) -> None:
        reason = hcfr.unavailable_reason()
        connected = self.app.session is not None
        if reason:
            self.enable_chk.state(["disabled"])
            self.status_lbl.configure(text=reason)
        else:
            self.enable_chk.state(["!disabled"] if connected else ["disabled"])
            self.status_lbl.configure(text="" if connected else "Connect to a VTG first.")
        if not connected and self.watcher.running:
            self.watcher.stop()
            self.enable_var.set(False)
        self.test_send.state(["!disabled"] if connected else ["disabled"])

    def _toggle(self) -> None:
        if self.enable_var.get():
            self.watcher.start()
            self.status_lbl.configure(text="Watching…")
        else:
            self.watcher.stop()
            self.status_lbl.configure(text="Stopped.")

    def _apply(self, d: hcfr.Decision) -> None:
        self.status_lbl.configure(text=f"HCFR → {d}")
        self.app.log.info(f"HCFR → {d}")
        if d.color:
            self.app.control.set_color(d.color)
        elif d.ire is not None:
            self.app.control.set_ire(d.ire)

    def _test(self) -> hcfr.Decision | None:
        d = hcfr.decide(self.test_text.get("1.0", "end"))
        self.test_lbl.configure(text=str(d) if d else "nothing")
        return d

    def _send_test(self) -> None:
        d = self._test()
        if d:
            self._apply(d)
