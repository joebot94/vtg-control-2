"""Where user data lives, in a source checkout and in a PyInstaller exe.

Frozen one-file exes unpack to a temp dir that is deleted on exit, so
presets/ and captures/ go next to the .exe instead. Bundled example
presets are copied there on first run.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def app_dir() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundle_dir() -> Path:
    """Read-only files shipped with the app."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return app_dir()


def data_dir(name: str) -> Path:
    """app_dir()/name, created on demand; seeded from the bundle if new."""
    path = app_dir() / name
    if not path.exists():
        seed = bundle_dir() / name
        if FROZEN and seed.is_dir():
            shutil.copytree(seed, path)
        else:
            path.mkdir(parents=True, exist_ok=True)
    return path
