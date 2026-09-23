"""LAB page: live TX/RX log, ASCII/HEX view, raw command entry, JSONL capture."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vtg.capture import ERR, INFO, RX, TX, Event, load_jsonl, parse_escapes, save_jsonl, to_ascii, to_hex

from . import theme

CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures"
MAX_LINES = 5000


class LabPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.viewing: tuple[str, list[Event]] | None = None  # (filename, events) when showing a file
        # ids of events a rerender already drew; their queued live copies are skipped
        self._drawn_ids: set[int] = set()

        # ---- toolbar ----
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        self.view_var = tk.StringVar(value="ascii")
        for val, text in (("ascii", "ASCII"), ("hex", "HEX"), ("both", "BOTH")):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.view_var,
                            command=self.rerender, style="Bar.TRadiobutton").pack(side="left", padx=(0, 8))
        self.show_info_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Info", variable=self.show_info_var, command=self.rerender,
                        style="Bar.TCheckbutton").pack(side="left", padx=(8, 0))
        self.poll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Poll VTG status", variable=self.poll_var,
                        command=self._toggle_poll, style="Bar.TCheckbutton").pack(side="left", padx=(12, 0))

        ttk.Button(bar, text="Save capture…", command=self.save_capture).pack(side="right")
        ttk.Button(bar, text="Open capture…", command=self.open_capture).pack(side="right", padx=6)
        self.live_btn = ttk.Button(bar, text="Back to live", command=self.back_to_live)
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="right")

        self.banner = ttk.Label(self, text="", style="Dim.TLabel")
        self.banner.pack(fill="x")

        # ---- log ----
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        self.text = tk.Text(wrap, bg=theme.PANEL, fg=theme.FG, font=app.fonts["mono"],
                            insertbackground=theme.FG, relief="flat", borderwidth=0,
                            highlightthickness=1, highlightbackground=theme.LINE,
                            highlightcolor=theme.LINE, wrap="none", padx=8, pady=6,
                            selectbackground=theme.ACCENT, selectforeground="#000000")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure(TX, foreground=theme.ACCENT)
        self.text.tag_configure(RX, foreground=theme.OK)
        self.text.tag_configure(INFO, foreground=theme.FG_DIM)
        self.text.tag_configure(ERR, foreground=theme.ERR)
        self.text.tag_configure("time", foreground=theme.FG_DIM)

        # ---- raw entry ----
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="RAW", style="Title.TLabel").pack(side="left", padx=(0, 8))
        self.raw_var = tk.StringVar()
        self.raw_entry = ttk.Entry(row, textvariable=self.raw_var, font=app.fonts["mono"])
        self.raw_entry.pack(side="left", fill="x", expand=True)
        self.raw_entry.bind("<Return>", lambda e: self.send_raw())
        self.raw_entry.bind("<Up>", lambda e: self._history(-1))
        self.raw_entry.bind("<Down>", lambda e: self._history(1))
        self.cr_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="+\\r", variable=self.cr_var,
                        style="Bar.TCheckbutton").pack(side="left", padx=8)
        self.send_btn = ttk.Button(row, text="SEND", style="Accent.TButton", command=self.send_raw)
        self.send_btn.pack(side="left")
        ttk.Label(self, text="Escapes: \\r \\n \\e (Esc) \\xNN \\\\   ·   ↑/↓ history   ·   "
                            "raw sends go through the same queue as everything else",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 0))
        self._hist: list[str] = []
        self._hist_pos = 0

        s = ttk.Style()
        s.configure("Bar.TRadiobutton", background=theme.BG)
        s.map("Bar.TRadiobutton", background=[("active", theme.BG)])
        s.configure("Bar.TCheckbutton", background=theme.BG)
        s.map("Bar.TCheckbutton", background=[("active", theme.BG)])

        app.on_event(self._on_event)
        app.on_state_change(self._on_state)
        self._on_state()

    # ----------------------------------------------------------- render --
    def _line(self, ev: Event) -> list[tuple[str, str]]:
        """(text, tag) chunks for one event."""
        parts = [(ev.clock() + " ", "time"), (f"{ev.dir:<4} ", ev.dir)]
        if ev.data:
            mode = self.view_var.get()
            if mode == "ascii":
                body = to_ascii(ev.data)
            elif mode == "hex":
                body = to_hex(ev.data)
            else:
                body = f"{to_ascii(ev.data):<28} | {to_hex(ev.data)}"
            parts.append((body, ev.dir))
        if ev.note:
            parts.append(((" · " if ev.data else "") + ev.note, INFO if ev.dir != ERR else ERR))
        parts.append(("\n", ""))
        return parts

    def _append(self, events: list[Event]) -> None:
        at_bottom = self.text.yview()[1] > 0.999
        self.text.configure(state="normal")
        for ev in events:
            if ev.dir == INFO and not self.show_info_var.get():
                continue
            for chunk, tag in self._line(ev):
                self.text.insert("end", chunk, tag)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > MAX_LINES:
            self.text.delete("1.0", f"{lines - MAX_LINES}.0")
        self.text.configure(state="disabled")
        if at_bottom:
            self.text.see("end")

    def rerender(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        events = self.viewing[1] if self.viewing else self.app.log.events()
        self._drawn_ids = {id(e) for e in events[-500:]}
        self._append(events)

    def _on_event(self, ev: Event) -> None:
        if id(ev) in self._drawn_ids:
            self._drawn_ids.discard(id(ev))
        elif not self.viewing:
            self._append([ev])

    def _on_state(self) -> None:
        self.send_btn.state(["!disabled"] if self.app.session else ["disabled"])

    # ---------------------------------------------------------- actions --
    def _toggle_poll(self) -> None:
        self.app.polling_enabled = self.poll_var.get()
        self.app.log.info("status polling " + ("on" if self.app.polling_enabled else "off"))

    def clear(self) -> None:
        if self.viewing:
            self.back_to_live()
        self.app.log.clear()
        self.rerender()

    def send_raw(self) -> None:
        text = self.raw_var.get()
        if not text or not self.app.session:
            return
        try:
            data = parse_escapes(text)
        except ValueError as exc:
            self.app.log.error(f"raw entry: {exc}")
            return
        if self.cr_var.get():
            data += b"\r"
        if not self._hist or self._hist[-1] != text:
            self._hist.append(text)
        self._hist_pos = len(self._hist)
        self.raw_var.set("")
        if self.viewing:
            self.back_to_live()
        self.app.session.vtg.send_raw(data)  # reply shows up in the log by itself

    def _history(self, step: int) -> str:
        if self._hist:
            self._hist_pos = max(0, min(len(self._hist), self._hist_pos + step))
            self.raw_var.set(self._hist[self._hist_pos] if self._hist_pos < len(self._hist) else "")
            self.raw_entry.icursor("end")
        return "break"

    def save_capture(self) -> None:
        events = self.viewing[1] if self.viewing else self.app.log.events()
        if not events:
            return
        CAPTURE_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self, title="Save capture", initialdir=CAPTURE_DIR,
            initialfile=time.strftime("capture_%Y%m%d_%H%M%S.jsonl"),
            defaultextension=".jsonl", filetypes=[("JSON Lines capture", "*.jsonl")])
        if path:
            save_jsonl(events, path)
            self.banner.configure(text=f"Saved {len(events)} events → {path}")

    def open_capture(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Open capture", initialdir=CAPTURE_DIR,
                                          filetypes=[("JSON Lines capture", "*.jsonl")])
        if path:
            self.show_file(path)

    def show_file(self, path: str | Path) -> None:
        try:
            events = load_jsonl(path)
        except (ValueError, KeyError, OSError) as exc:
            messagebox.showerror("Can't open capture", str(exc), parent=self)
            return
        self.viewing = (Path(path).name, events)
        self.banner.configure(text=f"VIEWING FILE {Path(path).name} — {len(events)} events "
                                   f"(live traffic hidden)", foreground=theme.WARN)
        self.live_btn.pack(side="right", padx=6)
        self.rerender()

    def back_to_live(self) -> None:
        self.viewing = None
        self.banner.configure(text="", foreground=theme.FG_DIM)
        self.live_btn.pack_forget()
        self.rerender()
