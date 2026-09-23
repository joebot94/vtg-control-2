"""Byte transports: the only code that touches the physical port.

A Transport moves raw bytes and records every one of them in the CaptureLog.
It knows nothing about VTG commands. Only the SerialWorker (worker.py) may
call write/readline — the UI and protocol layers go through the worker, so
there is exactly one reader on the port.

SerialTransport  — real RS-232 via pyserial.
MockTransport    — an in-memory fake VTG so the whole app runs without
                   hardware. Its replies are GUESSES shaped to satisfy the
                   old app's parsers; they are not captured VTG output.
"""

from __future__ import annotations

import random
import re
import threading
import time
from abc import ABC, abstractmethod

from .capture import CaptureLog

DEFAULT_BAUD = 9600


class TransportError(Exception):
    pass


class Transport(ABC):
    is_mock = False
    label = "?"

    def __init__(self, log: CaptureLog):
        self.log = log

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    def write(self, data: bytes) -> None:
        self.log.tx(data)
        self._write(data)

    def readline(self, timeout: float) -> bytes:
        """Read one line ending in \\n. On timeout returns b"" or, if bytes
        arrived without a terminator, that partial data (the caller decides)."""
        line = self._readline(timeout)
        if line:
            self.log.rx(line, note="" if line.endswith(b"\n") else "partial: no line end before timeout")
        return line

    def drain(self) -> bytes:
        """Discard-and-log anything already waiting (unsolicited or stale)."""
        data = self._drain()
        if data:
            self.log.rx(data, note="unsolicited")
        return data

    @abstractmethod
    def _write(self, data: bytes) -> None: ...

    @abstractmethod
    def _readline(self, timeout: float) -> bytes: ...

    @abstractmethod
    def _drain(self) -> bytes: ...


class SerialTransport(Transport):
    def __init__(self, log: CaptureLog, port: str, baud: int = DEFAULT_BAUD):
        super().__init__(log)
        self.port_name = port
        self.baud = baud
        self.label = f"{port} / {baud}"
        self._ser = None

    def connect(self) -> None:
        import serial  # imported lazily so the mock runs without pyserial

        try:
            # serial_for_url takes COM3 / /dev/cu.* as-is, and also loop:// for tests
            self._ser = serial.serial_for_url(self.port_name, baudrate=self.baud, timeout=0.5,
                                              bytesize=8, parity="N", stopbits=1)
        except Exception as exc:  # noqa: BLE001
            raise TransportError(f"open {self.port_name}: {exc}") from exc
        self.log.info(f"opened {self.label} 8N1")

    def disconnect(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None
                self.log.info(f"closed {self.port_name}")

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def _write(self, data: bytes) -> None:
        if not self.is_connected:
            raise TransportError("port not open")
        self._ser.write(data)
        self._ser.flush()

    def _readline(self, timeout: float) -> bytes:
        if not self.is_connected:
            raise TransportError("port not open")
        self._ser.timeout = timeout
        return self._ser.readline()

    def _drain(self) -> bytes:
        if not self.is_connected:
            return b""
        n = self._ser.in_waiting
        return self._ser.read(n) if n else b""


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


# ---------------------------------------------------------------- mock ----


class _FakeVTG:
    """Just enough VTG state to answer the commands the app sends.

    Reply formats follow the SIS table in Extron's VTG 400D/400 DVI manual
    (rev C, pp. 3-6..3-10): set commands echo a tag (Pwr1, Tst09, Vlv50,
    Col7, Rte1*99), views return the bare value. Zero padding is a guess.
    """

    def __init__(self) -> None:
        self.power = 1
        self.ire = 50
        self.pattern = 17
        self.color = 7
        self.rate = (1, 99)
        self.temp_f = 96.0

    def handle(self, cmd: str) -> str:
        c = cmd.upper() if len(cmd) <= 2 else cmd  # single-letter commands are case-insensitive
        if c == "N":
            return "60-564-01"
        if c == "Q":
            return "2.00"
        if c == "*Q":
            return "2.00.0001"
        if c == "I":
            return f"Pat{self.pattern:02d} Rte{self.rate[0]:03d} Grp{self.rate[1]} Tmo0 Asq1"
        if m := re.fullmatch(r"([01])P", c):
            self.power = int(m[1])
            return f"Pwr{self.power}"
        if c == "P":
            return str(self.power)
        if m := re.fullmatch(r"(\d{1,3})\*15#", cmd):
            self.ire = int(m[1])
            return f"Vlv{self.ire}"
        if cmd == "15#":
            return str(self.ire)
        if m := re.fullmatch(r"(\d{1,2})J", c):
            if not 1 <= int(m[1]) <= 28:
                return "E07"
            self.pattern = int(m[1])
            return f"Tst{self.pattern:02d}"
        if c == "J":
            return f"{self.pattern:02d}"
        if m := re.fullmatch(r"([0-7])\*10#", cmd):
            self.color = int(m[1])
            return f"Col{self.color}"
        if cmd == "10#":
            return str(self.color)
        if m := re.fullmatch(r"(\d{1,3})\*(\d{1,2})=", cmd):
            self.rate = (int(m[1]), int(m[2]))
            return f"Rte{self.rate[0]}*{self.rate[1]}"
        if cmd == "=":
            return f"{self.rate[0]}*{self.rate[1]}"
        if cmd == "20S":
            self.temp_f += random.uniform(-0.4, 0.5)
            return f"{round(self.temp_f):03d}F  {round((self.temp_f - 32) / 1.8):02d}C"
        return "E10"  # Extron's generic "invalid command"


class MockTransport(Transport):
    is_mock = True
    label = "MOCK"
    reply_delay = 0.02  # seconds, roughly one 9600-baud reply

    def __init__(self, log: CaptureLog):
        super().__init__(log)
        self._vtg = _FakeVTG()
        self._rx = bytearray()
        self._ready_at = 0.0
        self._cv = threading.Condition()
        self._open = False

    def connect(self) -> None:
        self._open = True
        self.log.info("opened MOCK transport (fake VTG, replies are not real)")

    def disconnect(self) -> None:
        self._open = False
        self.log.info("closed MOCK transport")

    @property
    def is_connected(self) -> bool:
        return self._open

    def _write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("port not open")
        reply = self._vtg.handle(data.decode("ascii", errors="replace").strip())
        with self._cv:
            self._rx += reply.encode("ascii") + b"\r\n"
            self._ready_at = time.monotonic() + self.reply_delay
            self._cv.notify_all()

    def _readline(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                now = time.monotonic()
                nl = self._rx.find(b"\n")
                if nl >= 0 and now >= self._ready_at:
                    line = bytes(self._rx[: nl + 1])
                    del self._rx[: nl + 1]
                    return line
                if now >= deadline:
                    return b""
                wake = deadline if nl < 0 else min(deadline, self._ready_at)
                self._cv.wait(max(0.001, wake - now))

    def _drain(self) -> bytes:
        with self._cv:
            data = bytes(self._rx)
            self._rx.clear()
            return data
