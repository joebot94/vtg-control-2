"""Main window: connection bar, tabbed pages, status bar.

Threading rule: the serial worker thread never touches Tk. Log events and
finished Futures are handed to the Tk thread through one queue that
`_pump` drains every 40 ms.
"""

from __future__ import annotations

import queue
import tkinter as tk
from concurrent.futures import Future
from tkinter import ttk
from typing import Callable

from vtg.capture import ERR, RX, CaptureLog, Event, to_ascii
from vtg.session import MOCK_PORT, Session, open_session
from vtg.transport import TransportError, list_serial_ports

from . import theme
from .control import ControlPage
from .hcfr import HCFRPage
from .lab import LabPage
from .presets import PresetsPage
from .timings import TimingsPage

APP_NAME = "JOEBOT VTG"
BAUDS = ["9600", "19200", "38400", "57600", "115200"]
POLL_STATUS_MS = 10_000      # IRE / pattern / resolution
POLL_TEMPERATURE_MS = 30_000


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log = CaptureLog()
        self.session: Session | None = None
        self.model = "—"
        self._q: queue.Queue = queue.Queue()
        self._event_listeners: list[Callable[[Event], None]] = []
        self._state_listeners: list[Callable[[], None]] = []
        self._poll_jobs: dict[str, str] = {}
        self._recent_errors = 0

        root.title(APP_NAME)
        root.geometry("900x680")
        root.minsize(760, 560)
        theme.apply(root)
        self.fonts = theme.fonts()

        self.log.subscribe(lambda ev: self._q.put(("event", ev)))

        self._build_header()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.control = ControlPage(self.notebook, self)
        self.timings = TimingsPage(self.notebook, self)
        self.presets = PresetsPage(self.notebook, self)
        self.hcfr = HCFRPage(self.notebook, self)
        self.lab = LabPage(self.notebook, self)
        for page, text in ((self.control, "CONTROL"), (self.timings, "TIMINGS"),
                           (self.presets, "PRESETS"), (self.hcfr, "HCFR"), (self.lab, "LAB")):
            self.notebook.add(page, text=text)
        self._build_status()

        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._set_state_ui()
        root.after(40, self._pump)

    # ------------------------------------------------------------ layout --
    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        bar.pack(fill="x")
        self.conn_dot = theme.Dot(bar)
        self.conn_dot.pack(side="left", padx=(0, 6))
        self.model_lbl = ttk.Label(bar, text=APP_NAME, style="Title.TLabel")
        self.model_lbl.pack(side="left")

        right = ttk.Frame(bar)
        right.pack(side="right")
        ttk.Label(right, text="Port", style="Dim.TLabel").pack(side="left", padx=(0, 4))
        self.port_var = tk.StringVar(value=MOCK_PORT)
        self.port_box = ttk.Combobox(right, textvariable=self.port_var, width=18)
        self.port_box.pack(side="left")
        self.port_box.bind("<Button-1>", lambda e: self._refresh_ports())
        ttk.Label(right, text="Baud", style="Dim.TLabel").pack(side="left", padx=(10, 4))
        self.baud_var = tk.StringVar(value="9600")
        self.baud_box = ttk.Combobox(right, textvariable=self.baud_var, values=BAUDS,
                                     width=7, state="readonly")
        self.baud_box.pack(side="left")
        self.conn_btn = ttk.Button(right, text="Connect", style="Accent.TButton",
                                   command=self.toggle_connection, width=11)
        self.conn_btn.pack(side="left", padx=(10, 0))
        self._refresh_ports()

    def _build_status(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 4, 10, 6))
        bar.pack(fill="x", side="bottom")
        self.health_lbl = ttk.Label(bar, text="OFFLINE", style="Dim.TLabel")
        self.health_lbl.pack(side="right")
        self.health_dot = theme.Dot(bar)
        self.health_dot.pack(side="right", padx=(0, 6))
        self.last_lbl = ttk.Label(bar, text="", style="Dim.TLabel", font=self.fonts["mono"])
        self.last_lbl.pack(side="left", fill="x", expand=True)

    def _refresh_ports(self) -> None:
        self.port_box["values"] = [MOCK_PORT] + list_serial_ports()

    # -------------------------------------------------------- connection --
    def toggle_connection(self) -> None:
        if self.session:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        port = self.port_var.get().strip()
        if not port:
            return
        try:
            self.session = open_session(port, int(self.baud_var.get()), self.log)
        except TransportError as exc:
            self.log.error(str(exc))
            self.session = None
            self._set_state_ui()
            return
        self.model = "…"
        self._recent_errors = 0
        self._set_state_ui()
        self.when_done(self.session.vtg.identify(), self._on_identified)

    def _on_identified(self, fut: Future) -> None:
        try:
            self.model = fut.result()
        except Exception:  # noqa: BLE001 — logged by worker
            self.model = "No reply"
        self._set_state_ui()
        self._start_polling()

    def disconnect(self) -> None:
        self._stop_polling()
        if self.session:
            self.session.close()
        self.session = None
        self.model = "—"
        self._set_state_ui()

    def _set_state_ui(self) -> None:
        s = self.session
        if s:
            self.model_lbl.configure(text=f"{self.model}   {s.label}")
            self.conn_dot.set(theme.WARN if s.is_mock else theme.OK)
            self.conn_btn.configure(text="Disconnect")
            self.port_box.configure(state="disabled")
            self.baud_box.configure(state="disabled")
        else:
            self.model_lbl.configure(text=APP_NAME)
            self.conn_dot.set(theme.FG_DIM)
            self.conn_btn.configure(text="Connect")
            self.port_box.configure(state="normal")
            self.baud_box.configure(state="readonly")
        self._update_health()
        for fn in self._state_listeners:
            fn()

    # ----------------------------------------------------------- polling --
    def _start_polling(self) -> None:
        self._stop_polling()
        self.poll_status()
        self.poll_temperature()

    def _stop_polling(self) -> None:
        for job in self._poll_jobs.values():
            self.root.after_cancel(job)
        self._poll_jobs.clear()

    def _reschedule(self, ms: int, fn: Callable[[], None]) -> None:
        self._poll_jobs[fn.__name__] = self.root.after(ms, fn)

    def poll_status(self) -> None:
        # All queries go through the one worker queue; skip if it's backed up.
        if self.session and self.session.worker.pending() < 3:
            self.control.refresh_from_device()
        if self.session:
            self._reschedule(POLL_STATUS_MS, self.poll_status)

    def poll_temperature(self) -> None:
        if self.session and self.session.worker.pending() < 3:
            self.control.refresh_temperature()
        if self.session:
            self._reschedule(POLL_TEMPERATURE_MS, self.poll_temperature)

    # --------------------------------------------------- thread bridging --
    def when_done(self, fut: Future, callback: Callable[[Future], None]) -> None:
        """Run callback(fut) on the Tk thread once the Future finishes."""
        fut.add_done_callback(lambda f: self._q.put(("future", callback, f)))

    def on_event(self, fn: Callable[[Event], None]) -> None:
        self._event_listeners.append(fn)

    def on_state_change(self, fn: Callable[[], None]) -> None:
        self._state_listeners.append(fn)

    def _pump(self) -> None:
        try:
            for _ in range(500):
                item = self._q.get_nowait()
                if item[0] == "event":
                    self._handle_event(item[1])
                else:
                    item[1](item[2])
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def _handle_event(self, ev: Event) -> None:
        if ev.dir == ERR:
            self._recent_errors += 1
        elif ev.dir == RX:
            self._recent_errors = 0
        text = to_ascii(ev.data) if ev.data else ev.note
        self.last_lbl.configure(text=f"{ev.clock()} {ev.dir:<4} {text}"[:110])
        self._update_health()
        for fn in self._event_listeners:
            fn(ev)

    def _update_health(self) -> None:
        if not self.session:
            color, text = theme.FG_DIM, "OFFLINE"
        elif self._recent_errors >= 3:
            color, text = theme.ERR, "NO REPLY"
        elif self._recent_errors:
            color, text = theme.WARN, "ERRORS"
        elif self.session.is_mock:
            color, text = theme.WARN, "MOCK"
        else:
            color, text = theme.OK, "HEALTHY"
        self.health_dot.set(color)
        self.health_lbl.configure(text=text, foreground=color)

    def quit(self) -> None:
        self.disconnect()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
