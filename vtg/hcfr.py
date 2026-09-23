"""HCFR integration: watch HCFR's "Information" window and follow it.

Ported from the May 2025 app. Two halves:

  decide(text)  — pure: HCFR window text -> what the VTG should show.
                  Same rules as before: colour cues first, else "NN% gray"
                  rounded to the nearest 10 IRE.
  HCFRWatcher   — Windows only: finds visible windows titled "Information",
                  reads them via UI Automation (pywinauto) plus an OCR
                  fallback (pytesseract), calls decide(), and reports only
                  when the answer changes (the old app re-sent every 0.5 s).

The watcher runs on its own thread and never touches the serial port; the
UI turns its decisions into VTGProtocol calls.
"""

from __future__ import annotations

import re
import sys
import threading
from dataclasses import dataclass
from typing import Callable

POLL_INTERVAL = 0.5

# case-insensitive HCFR cue -> VTG colour name (protocol.COLORS key)
COLOR_CUES = {
    "red primary": "Red",
    "green primary": "Green",
    "blue primary": "Blue",
    "cyan secondary": "Cyan",
    "magenta secondary": "Magenta",
    "yellow secondary": "Yellow",
    "white": "White",
}


@dataclass(frozen=True)
class Decision:
    color: str | None = None
    ire: int | None = None

    def __str__(self) -> str:
        return f"color {self.color}" if self.color else f"IRE {self.ire}"


def decide(text: str) -> Decision | None:
    low = text.lower()
    for cue, color in COLOR_CUES.items():
        if cue in low:
            return Decision(color=color)
    m = re.search(r"(\d{1,3})%\s*gray", text, re.IGNORECASE)
    if m and 0 <= int(m[1]) <= 100:
        # nearest 10, halves up (the old app's round() sent 25% -> 20 but 35% -> 40)
        return Decision(ire=(int(m[1]) + 5) // 10 * 10)
    return None


def unavailable_reason() -> str | None:
    """None if the watcher can run here, else why not."""
    if sys.platform != "win32":
        return "HCFR watching needs Windows (UI Automation)."
    try:
        import pywinauto  # noqa: F401
        import win32gui  # noqa: F401
    except ImportError as exc:
        return f"Missing Windows package: {exc.name} (pip install pywinauto pywin32)"
    return None


def _read_information_windows() -> str:
    import win32gui
    from pywinauto import Desktop

    handles: list[int] = []

    def cb(h, acc):
        if win32gui.IsWindowVisible(h) and "Information" in win32gui.GetWindowText(h):
            acc.append(h)
    win32gui.EnumWindows(cb, handles)

    chunks = []
    for h in handles:
        try:
            dlg = Desktop(backend="uia").window(handle=h)
            chunks += [c.window_text() for c in dlg.descendants() if c.window_text()]
        except Exception:  # noqa: BLE001 — window may vanish mid-read
            pass
        try:  # OCR fallback, optional
            import pytesseract
            from PIL import ImageGrab
            chunks.append(pytesseract.image_to_string(ImageGrab.grab(win32gui.GetWindowRect(h))))
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(chunks)


class HCFRWatcher:
    def __init__(self, on_decision: Callable[[Decision], None],
                 read_text: Callable[[], str] = _read_information_windows):
        self._on_decision = on_decision
        self._read = read_text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: Decision | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.set()  # retire any previous thread; each run gets its own flag
        self._stop = threading.Event()
        self._last = None
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        daemon=True, name="hcfr")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, stop: threading.Event) -> None:
        while not stop.wait(POLL_INTERVAL):
            try:
                d = decide(self._read())
            except Exception:  # noqa: BLE001 — keep watching
                continue
            if d is not None and d != self._last and not stop.is_set():
                self._last = d
                self._on_decision(d)
