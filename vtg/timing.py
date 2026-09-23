"""Video timing model and derived-value math.

A Timing holds integer pixel/line counts plus ONE authoritative clock
figure. `clock_source` says which figure the user typed in:

    REFRESH      clock_value = vertical refresh, Hz
    H_FREQ       clock_value = horizontal line rate, Hz
    PIXEL_CLOCK  clock_value = pixel clock, Hz

The other two are derived from it and the totals. That way a preset can
say "exactly 15.734 kHz" or "exactly 6.293 MHz" without the rounding of
the other figures leaking back into it. Which figure the VTG itself
stores is unknown until we capture it — this model can follow either.

Progressive math:
    H total = active + front + sync + back   (same for V)
    pixel clock = H total × V total × refresh
    H freq      = pixel clock / H total
    refresh     = H freq / V total

Interlaced: NOT IMPLEMENTED. The flag is stored and round-trips through
presets, but derived values are computed as if progressive, and
`warnings()` says so. Settle how the VTG counts interlaced lines (per
frame vs per field, half-line) from captures before adding the math.

Generators (CVT, CVT-RB, GTF, CRT-style) would be functions returning a
Timing and register in GENERATORS; only manual entry exists today.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Callable


class ClockSource(str, Enum):
    REFRESH = "refresh"
    H_FREQ = "h_freq"
    PIXEL_CLOCK = "pixel_clock"


class TimingError(ValueError):
    pass


POLARITIES = ("+", "-")


@dataclass
class Timing:
    name: str = "Untitled"

    width: int = 640
    height: int = 480

    h_front_porch: int = 16
    h_sync_width: int = 96
    h_back_porch: int = 48

    v_front_porch: int = 10
    v_sync_width: int = 2
    v_back_porch: int = 33

    h_sync_polarity: str = "-"
    v_sync_polarity: str = "-"

    interlaced: bool = False

    clock_source: ClockSource = ClockSource.REFRESH
    clock_value: float = 59.94  # Hz; meaning set by clock_source

    # ---- totals ----
    @property
    def h_blank(self) -> int:
        return self.h_front_porch + self.h_sync_width + self.h_back_porch

    @property
    def v_blank(self) -> int:
        return self.v_front_porch + self.v_sync_width + self.v_back_porch

    @property
    def h_total(self) -> int:
        return self.width + self.h_blank

    @property
    def v_total(self) -> int:
        return self.height + self.v_blank

    # ---- clocks (all Hz) ----
    @property
    def pixel_clock(self) -> float:
        if self.clock_source is ClockSource.PIXEL_CLOCK:
            return self.clock_value
        if self.clock_source is ClockSource.H_FREQ:
            return self.clock_value * self.h_total
        return self.clock_value * self.h_total * self.v_total

    @property
    def h_freq(self) -> float:
        return self.pixel_clock / self.h_total if self.h_total else 0.0

    @property
    def refresh(self) -> float:
        return self.h_freq / self.v_total if self.v_total else 0.0

    def clock_for(self, source: ClockSource) -> float:
        return {
            ClockSource.REFRESH: self.refresh,
            ClockSource.H_FREQ: self.h_freq,
            ClockSource.PIXEL_CLOCK: self.pixel_clock,
        }[source]

    def with_clock_source(self, source: ClockSource) -> "Timing":
        """Same timing, different authoritative figure (value preserved)."""
        return replace(self, clock_source=source, clock_value=self.clock_for(source))

    # ---- checks ----
    def validate(self) -> None:
        ints = {
            "width": self.width, "height": self.height,
            "h_front_porch": self.h_front_porch, "h_sync_width": self.h_sync_width,
            "h_back_porch": self.h_back_porch, "v_front_porch": self.v_front_porch,
            "v_sync_width": self.v_sync_width, "v_back_porch": self.v_back_porch,
        }
        for key, val in ints.items():
            if not isinstance(val, int) or isinstance(val, bool):
                raise TimingError(f"{key} must be an integer")
            if val < 0:
                raise TimingError(f"{key} must not be negative")
        if self.width <= 0 or self.height <= 0:
            raise TimingError("active size must be positive")
        if self.h_sync_width <= 0 or self.v_sync_width <= 0:
            raise TimingError("sync width must be positive")
        for key in ("h_sync_polarity", "v_sync_polarity"):
            if getattr(self, key) not in POLARITIES:
                raise TimingError(f"{key} must be '+' or '-'")
        if not self.clock_value > 0:
            raise TimingError("clock value must be positive")

    def warnings(self) -> list[str]:
        out = []
        if self.interlaced:
            out.append("Interlaced math not implemented: values shown as progressive.")
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["clock_source"] = self.clock_source.value
        return d


# name -> function returning a Timing. Empty until CVT/GTF/etc. are written.
GENERATORS: dict[str, Callable[..., Timing]] = {}


def example_320x240() -> Timing:
    """Example manual timing — NOT verified canonical NTSC 240p.

    262 total lines like real 240p, but porches are placeholders; confirm
    against how the VTG itself represents 240p before trusting it.
    """
    return Timing(
        name="320x240 example (unverified)",
        width=320, height=240,
        h_front_porch=16, h_sync_width=32, h_back_porch=48,
        v_front_porch=3, v_sync_width=3, v_back_porch=16,
        h_sync_polarity="-", v_sync_polarity="-",
        interlaced=False,
        clock_source=ClockSource.REFRESH, clock_value=59.94,
    )
