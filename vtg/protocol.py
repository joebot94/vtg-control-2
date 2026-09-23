"""Extron VTG 400 command set and reply parsing.

Every Extron SIS string in the app lives in this file. The UI calls
methods like `vtg.set_resolution("240p")`; it never sees "001*99=".

Command strings were carried over from the working May 2025 app
(VTG400+HCFR.py / vtg400qt.py). Reply formats are documented in
Extron's VTG 400D/400 DVI manual (rev C, SIS table), but parsers stay
tolerant — they pull the number out of whatever comes back.

Custom timing: NOT IMPLEMENTED. The official Extron software programs
custom resolutions over RS-232 with a protocol we have not captured.
`encode_custom_timing` raises until it is reverse-engineered from real
captures. Do not guess at it.
"""

from __future__ import annotations

import re
from concurrent.futures import Future

from .timing import Timing
from .worker import SerialWorker

MODELS = {
    "60-564-01": "VTG 400",
    "60-564-02": "VTG 400D",
    "60-564-03": "VTG 400DVI",
}

RESOLUTIONS = {
    "240p":   "001*99=",
    "NTSC/U": "001*07=",
    "NTSC/J": "002*07=",
    "PAL":    "003*07=",
    "480p":   "001*06=",
    "576p":   "002*06=",
    "720p":   "004*06=",
    "1080i":  "010*06=",
}

# name -> pattern number for "{n}J".
# Numbers are the VTG's PatternIDs, as listed in the official software's hi.vtg
# (see docs/VTG_RATE_RECORD.md). The 9 the original app used all match that list.
PATTERNS = {
    # the original app's nine, in its button order (short names)
    "Window20":   15,
    "Window80":   14,
    "VarIRE":     16,
    "4x4Cross":    6,
    "Coarse":      7,
    "FineCross":   8,
    "ColorBar":   13,
    "FullScreen": 17,
    "PLUGE":       9,
    # the rest, with Extron's names (not yet exercised on hardware)
    "Circles":                  1,
    "Safe Area":                2,
    "Focus":                    3,
    "4:3 Crop":                 4,
    "Rect/Square Crosshairs":   5,
    "32-Level Split Grayscale": 10,
    "Extreme Grayscale":        11,
    "Ramp":                     12,
    "F.Field+Target":           18,
    "Checkerboard":             19,
    "Bounce (Automatic)":       20,
    "Bounce (Manual Toggle)":   21,
    "Alt. Pixels (1 On 1 Off)": 22,
    "Graphics Multiburst":      23,
    "Alt. Pixels 2D (1x1)":     24,
    "Transient Response":       25,
    "Cont. Transfer Function":  26,
    "H Pattern W On B":         27,
    "Hum Bar":                  28,
}
MAIN_PATTERNS = list(PATTERNS)[:9]   # buttons on CONTROL
MORE_PATTERNS = list(PATTERNS)[9:]   # the "More" dropdown

# From hi.vtg: the patterns whose look depends on IRE level, and those that can be inverted.
IRE_PATTERN_IDS = {16, 17, 18, 19, 26, 28}
INVERT_PATTERN_IDS = {1, 2, 4, 5, 6, 7, 8, 12, 19, 21, 26, 27}  # invert command not known yet


def pattern_uses_ire(name: str | None) -> bool:
    return name is not None and PATTERNS.get(name) in IRE_PATTERN_IDS

# name -> color code for "{code}*10#" (dict order = button order)
COLORS = {
    "Black":   0,
    "Red":     4,
    "Green":   2,
    "Blue":    1,
    "White":   7,
    "Magenta": 5,
    "Yellow":  6,
    "Cyan":    3,
}

IRE_STEP_CHOICES = (5, 10, 20, 25)
DEFAULT_IRE_STEP = 10


def ire_steps(step: int = DEFAULT_IRE_STEP) -> list[int]:
    """Button values 0..100 for a step size (100 always included)."""
    return list(range(0, 100, step)) + [100]


def nearest_ire(value: float, step: int = DEFAULT_IRE_STEP) -> int:
    """Nearest multiple of step within 0..100, halves rounding up."""
    return max(0, min(100, int(value + step / 2) // step * step))

SET_TIMEOUT = 0.6
QUERY_TIMEOUT = 1.0


class ProtocolError(Exception):
    pass


class NotCaptured(NotImplementedError):
    """Raised by anything that needs protocol knowledge we don't have yet."""


# ------------------------------------------------------------ parsers ----


def parse_model(reply: str) -> str:
    for part, name in MODELS.items():
        if part in reply:
            return name
    return f"Unknown ({reply})" if reply else "Unknown"


def parse_int(reply: str) -> int:
    """Last integer in the reply, e.g. "50", "Ire050" -> 50."""
    nums = re.findall(r"\d+", reply)
    if not nums:
        raise ProtocolError(f"no number in {reply!r}")
    return int(nums[-1])


def parse_resolution(reply: str) -> str | None:
    """Reply containing "nnn*nn" -> resolution name, or None if unknown."""
    m = re.search(r"(\d+\*\d+)", reply)
    if not m:
        raise ProtocolError(f"no resolution code in {reply!r}")
    # compare as numbers: the VTG may answer "1*99" for the "001*99=" command
    code = tuple(int(x) for x in m[1].split("*"))
    for name, cmd in RESOLUTIONS.items():
        if tuple(int(x) for x in cmd.rstrip("=").split("*")) == code:
            return name
    return None


def parse_temperature_f(reply: str) -> float:
    m = re.search(r"([+-]?\d+\.?\d*)\s*F", reply)
    if not m:
        raise ProtocolError(f"no temperature in {reply!r}")
    return float(m[1])


def parse_pattern(reply: str) -> str | None:
    n = parse_int(reply)
    return next((k for k, v in PATTERNS.items() if v == n), None)


def parse_color(reply: str) -> str | None:
    n = parse_int(reply)
    return next((k for k, v in COLORS.items() if v == n), None)


# ----------------------------------------------------------- protocol ----


class VTGProtocol:
    """High-level VTG operations. Every method returns a Future."""

    def __init__(self, worker: SerialWorker):
        self._w = worker

    def _set(self, cmd: str, parser=lambda line: line) -> Future:
        return self._w.send(cmd, timeout=SET_TIMEOUT, parser=parser, response_optional=True)

    def _query(self, cmd: str, parser) -> Future:
        return self._w.send(cmd, timeout=QUERY_TIMEOUT, parser=parser, retries=1)

    # identity / status
    def identify(self) -> Future:
        return self._query("N", parse_model)

    def query_ire(self) -> Future:
        return self._query("15#", parse_int)

    def query_pattern(self) -> Future:
        return self._query("J", parse_pattern)

    def query_resolution(self) -> Future:
        return self._query("=", parse_resolution)

    def query_temperature(self) -> Future:
        return self._query("20S", parse_temperature_f)

    # control
    def set_power(self, on: bool) -> Future:
        return self._set("1P" if on else "0P")

    def set_resolution(self, name: str) -> Future:
        if name not in RESOLUTIONS:
            raise ValueError(f"unknown resolution {name!r}")
        return self._set(RESOLUTIONS[name])

    def set_pattern(self, name: str) -> Future:
        if name not in PATTERNS:
            raise ValueError(f"unknown pattern {name!r}")
        return self._set(f"{PATTERNS[name]}J")

    def set_color(self, name: str) -> Future:
        if name not in COLORS:
            raise ValueError(f"unknown color {name!r}")
        return self._set(f"{COLORS[name]}*10#")

    def set_ire(self, value: int) -> Future:
        if not 0 <= value <= 100:
            raise ValueError(f"IRE {value} out of range 0-100")
        return self._set(f"{int(value)}*15#")

    def send_raw(self, data: bytes, timeout: float = 1.0) -> Future:
        """Serial Lab: send exact bytes, return the reply line (or None)."""
        return self._w.send(data, timeout=timeout, response_optional=True)

    # custom timing — stubbed until captured
    supports_custom_timing = False

    def encode_custom_timing(self, timing: Timing) -> bytes:
        raise NotCaptured(
            "VTG custom-timing upload protocol has not been captured yet. "
            "Capture the official Extron software first; see README."
        )

    def program_timing(self, timing: Timing) -> Future:
        timing.validate()
        encoded = self.encode_custom_timing(timing)  # raises NotCaptured today
        return self._w.send(encoded, timeout=3.0)
