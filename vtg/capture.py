"""TX/RX capture log.

Every byte that crosses the transport is recorded here as an Event. The log
fans events out to listeners (the Serial Lab, the status bar) and can be
saved/loaded as JSONL — one event per line — so tomorrow's capture of the
official Extron software lands in the same format as our own traffic and
can be diffed with the same tools.

JSONL line format:
    {"t": 1769999999.123, "dir": "TX", "hex": "30 30 31 2a 39 39 3d",
     "ascii": "001*99=", "note": ""}

`dir` is TX, RX, INFO or ERR. `hex` is authoritative; `ascii` is a
convenience rendering (non-printables escaped) and is ignored on load.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TX, RX, INFO, ERR = "TX", "RX", "INFO", "ERR"


def to_ascii(data: bytes) -> str:
    """Printable rendering: \\r \\n and other control bytes shown escaped."""
    out = []
    for b in data:
        if b == 0x0D:
            out.append("\\r")
        elif b == 0x0A:
            out.append("\\n")
        elif b == 0x1B:
            out.append("\\e")
        elif 0x20 <= b < 0x7F and b != 0x5C:
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def to_hex(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


@dataclass(frozen=True)
class Event:
    t: float
    dir: str
    data: bytes = b""
    note: str = ""

    def clock(self) -> str:
        lt = time.localtime(self.t)
        return time.strftime("%H:%M:%S", lt) + f".{int((self.t % 1) * 1000):03d}"

    def to_json(self) -> str:
        return json.dumps({
            "t": self.t,
            "dir": self.dir,
            "hex": to_hex(self.data),
            "ascii": to_ascii(self.data),
            "note": self.note,
        })

    @staticmethod
    def from_json(line: str) -> "Event":
        d = json.loads(line)
        hex_str = d.get("hex", "")
        return Event(
            t=float(d["t"]),
            dir=d["dir"],
            data=bytes.fromhex(hex_str) if hex_str else b"",
            note=d.get("note", ""),
        )


class CaptureLog:
    """Thread-safe event store. Listeners are called on the emitting thread."""

    def __init__(self, max_events: int = 20000):
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Event], None]] = []
        self._max = max_events

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    def emit(self, direction: str, data: bytes = b"", note: str = "") -> Event:
        ev = Event(time.time(), direction, bytes(data), note)
        with self._lock:
            self._events.append(ev)
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]
        for fn in self._listeners:
            fn(ev)
        return ev

    def tx(self, data: bytes, note: str = "") -> Event:
        return self.emit(TX, data, note)

    def rx(self, data: bytes, note: str = "") -> Event:
        return self.emit(RX, data, note)

    def info(self, note: str) -> Event:
        return self.emit(INFO, b"", note)

    def error(self, note: str) -> Event:
        return self.emit(ERR, b"", note)

    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def save_jsonl(events: list[Event], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for ev in events:
            f.write(ev.to_json() + "\n")


def load_jsonl(path: str | Path) -> list[Event]:
    with open(path, encoding="utf-8") as f:
        return [Event.from_json(line) for line in f if line.strip()]


def parse_escapes(text: str) -> bytes:
    """Raw-entry text -> bytes. Understands \\r \\n \\t \\e \\0 \\\\ and \\xNN."""
    out = bytearray()
    i = 0
    simple = {"r": 0x0D, "n": 0x0A, "t": 0x09, "e": 0x1B, "0": 0x00, "\\": 0x5C}
    while i < len(text):
        ch = text[i]
        if ch != "\\" or i + 1 >= len(text):
            out += ch.encode("latin-1")
            i += 1
            continue
        nxt = text[i + 1]
        if nxt in simple:
            out.append(simple[nxt])
            i += 2
        elif nxt == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", text[i + 2:i + 4]):
            out.append(int(text[i + 2:i + 4], 16))
            i += 4
        else:
            raise ValueError(f"bad escape \\{nxt} at position {i}")
    return bytes(out)
