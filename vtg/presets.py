"""Timing presets as human-readable JSON, one file per preset.

The authoritative clock is stored under the key named by `clock_source`
("refresh", "h_freq" or "pixel_clock", all in Hz). A "derived" block is
written for humans reading the file and is ignored on load.

    {
      "name": "320x240 example (unverified)",
      "width": 320, "height": 240,
      "clock_source": "refresh",
      "refresh": 59.94,
      "h_front_porch": 16, "h_sync_width": 32, "h_back_porch": 48,
      "v_front_porch": 3,  "v_sync_width": 3,  "v_back_porch": 16,
      "h_sync_polarity": "-", "v_sync_polarity": "-",
      "interlaced": false,
      "derived": {"h_total": 416, "v_total": 262, ...}
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .timing import ClockSource, Timing, TimingError

PRESET_DIR = Path(__file__).resolve().parents[1] / "presets"

_INT_FIELDS = ("width", "height",
               "h_front_porch", "h_sync_width", "h_back_porch",
               "v_front_porch", "v_sync_width", "v_back_porch")


def timing_to_dict(t: Timing) -> dict:
    d: dict = {"name": t.name, "width": t.width, "height": t.height,
               "clock_source": t.clock_source.value,
               t.clock_source.value: t.clock_value}
    for key in _INT_FIELDS[2:]:
        d[key] = getattr(t, key)
    d.update(h_sync_polarity=t.h_sync_polarity, v_sync_polarity=t.v_sync_polarity,
             interlaced=t.interlaced)
    d["derived"] = {
        "h_total": t.h_total, "v_total": t.v_total,
        "pixel_clock_hz": round(t.pixel_clock, 3),
        "h_freq_hz": round(t.h_freq, 4),
        "refresh_hz": round(t.refresh, 6),
    }
    return d


def timing_from_dict(d: dict) -> Timing:
    try:
        source = ClockSource(d.get("clock_source", "refresh"))
    except ValueError as exc:
        raise TimingError(f"unknown clock_source {d.get('clock_source')!r}") from exc
    if source.value not in d:
        raise TimingError(f"preset has clock_source {source.value!r} but no {source.value!r} value")
    kwargs = {k: int(d[k]) for k in _INT_FIELDS if k in d}
    t = Timing(
        name=str(d.get("name", "Untitled")),
        h_sync_polarity=d.get("h_sync_polarity", "-"),
        v_sync_polarity=d.get("v_sync_polarity", "-"),
        interlaced=bool(d.get("interlaced", False)),
        clock_source=source,
        clock_value=float(d[source.value]),
        **kwargs,
    )
    t.validate()
    return t


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return s or "preset"


def save(t: Timing, path: str | Path | None = None) -> Path:
    t.validate()
    path = Path(path) if path else PRESET_DIR / f"{slug(t.name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timing_to_dict(t), indent=2) + "\n", encoding="utf-8")
    return path


def load(path: str | Path) -> Timing:
    return timing_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def list_presets(directory: str | Path = PRESET_DIR) -> list[Path]:
    return sorted(Path(directory).glob("*.json"), key=lambda p: p.name.lower())
