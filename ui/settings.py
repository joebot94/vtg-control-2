"""Tiny per-install UI settings (settings.json next to the app/exe)."""

from __future__ import annotations

import json

from vtg.paths import app_dir

PATH = app_dir() / "settings.json"


def load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**changes) -> None:
    data = load()
    data.update(changes)
    try:
        PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # read-only location: the setting just won't stick
