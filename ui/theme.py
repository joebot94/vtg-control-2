"""Dark industrial ttk theme (built on 'clam', which honours colours on
Windows, macOS and Linux alike — the native macOS theme ignores them)."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#1a1b1d"        # window
PANEL = "#232427"     # frames / fields
PANEL_HI = "#2e3034"  # buttons
LINE = "#3a3c41"      # borders
FG = "#d9d9d6"
FG_DIM = "#8b8d91"
ACCENT = "#ff8a1f"    # orange
ACCENT_DIM = "#8a4a12"
OK = "#3ecf6a"
WARN = "#e6b422"
ERR = "#e5484d"

if sys.platform == "win32":
    UI_FAMILY, MONO_FAMILY = "Segoe UI", "Consolas"
elif sys.platform == "darwin":
    UI_FAMILY, MONO_FAMILY = "Helvetica Neue", "Menlo"
else:
    UI_FAMILY, MONO_FAMILY = "DejaVu Sans", "DejaVu Sans Mono"


def fonts() -> dict[str, tuple]:
    return {
        "ui": (UI_FAMILY, 10),
        "ui_bold": (UI_FAMILY, 10, "bold"),
        "small": (UI_FAMILY, 9),
        "title": (UI_FAMILY, 12, "bold"),
        "mono": (MONO_FAMILY, 10),
        "mono_big": (MONO_FAMILY, 20, "bold"),
        "mono_mid": (MONO_FAMILY, 13, "bold"),
    }


def apply(root: tk.Tk) -> None:
    f = fonts()
    tkfont.nametofont("TkDefaultFont").configure(family=UI_FAMILY, size=10)
    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#000000")

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL,
                troughcolor=PANEL, focuscolor=ACCENT, font=f["ui"],
                selectbackground=ACCENT, selectforeground="#000000",
                insertcolor=FG)
    s.map(".", foreground=[("disabled", FG_DIM)])

    s.configure("TFrame", background=BG)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=FG)
    s.configure("Panel.TLabel", background=PANEL)
    s.configure("Dim.TLabel", foreground=FG_DIM)
    s.configure("PanelDim.TLabel", background=PANEL, foreground=FG_DIM)
    s.configure("Title.TLabel", font=f["title"], foreground=ACCENT)
    s.configure("Big.TLabel", background=PANEL, font=f["mono_big"], foreground=FG)
    s.configure("Mid.TLabel", background=PANEL, font=f["mono_mid"], foreground=FG)
    s.configure("Mono.TLabel", background=PANEL, font=f["mono"])
    s.configure("MonoAccent.TLabel", background=PANEL, font=f["mono"], foreground=ACCENT)
    s.configure("Warn.TLabel", background=PANEL, foreground=WARN)

    s.configure("TLabelframe", background=PANEL, bordercolor=LINE, relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=PANEL, foreground=ACCENT, font=f["ui_bold"])

    s.configure("TButton", background=PANEL_HI, foreground=FG, bordercolor=LINE,
                padding=(10, 4), relief="flat")
    s.map("TButton",
          background=[("disabled", PANEL), ("pressed", ACCENT_DIM), ("active", "#3a3d42")],
          foreground=[("disabled", FG_DIM)])
    s.configure("Accent.TButton", background=ACCENT, foreground="#000000", font=f["ui_bold"])
    s.map("Accent.TButton",
          background=[("disabled", PANEL_HI), ("pressed", ACCENT_DIM), ("active", "#ffa04a")],
          foreground=[("disabled", FG_DIM)])
    # Selected-state button used for "this is what the VTG is doing" highlighting
    s.configure("On.TButton", background=ACCENT, foreground="#000000")
    s.map("On.TButton", background=[("active", "#ffa04a"), ("pressed", ACCENT_DIM)])

    s.configure("TEntry", fieldbackground=PANEL_HI, foreground=FG, bordercolor=LINE,
                insertcolor=FG, padding=3)
    s.configure("TSpinbox", fieldbackground=PANEL_HI, foreground=FG, bordercolor=LINE,
                arrowcolor=FG, background=PANEL_HI, padding=2)
    s.configure("TCombobox", fieldbackground=PANEL_HI, foreground=FG, background=PANEL_HI,
                arrowcolor=FG, bordercolor=LINE, padding=2)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL_HI)],
          foreground=[("readonly", FG)], selectbackground=[("readonly", PANEL_HI)],
          selectforeground=[("readonly", FG)])
    s.configure("TCheckbutton", background=PANEL, foreground=FG, indicatorbackground=PANEL_HI,
                indicatorforeground=ACCENT)
    s.map("TCheckbutton", background=[("active", PANEL)],
          indicatorbackground=[("selected", PANEL_HI)])
    s.configure("TRadiobutton", background=PANEL, foreground=FG, indicatorbackground=PANEL_HI)
    s.map("TRadiobutton", background=[("active", PANEL)],
          indicatorforeground=[("selected", ACCENT)])

    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    s.configure("TNotebook.Tab", background=PANEL, foreground=FG_DIM, padding=(11, 5),
                font=f["ui_bold"], bordercolor=LINE)
    s.map("TNotebook.Tab",
          background=[("selected", PANEL_HI)],
          foreground=[("selected", ACCENT)])

    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                bordercolor=LINE, rowheight=22)
    s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#000000")])
    s.configure("Treeview.Heading", background=PANEL_HI, foreground=FG_DIM, relief="flat")
    for orient in ("Vertical", "Horizontal"):
        s.configure(f"{orient}.TScrollbar", background=PANEL_HI, troughcolor=PANEL,
                    bordercolor=LINE, arrowcolor=FG_DIM, lightcolor=PANEL_HI, darkcolor=PANEL_HI)


class Dot(tk.Canvas):
    """Small round status lamp."""

    def __init__(self, master, size: int = 12, color: str = FG_DIM, bg: str = BG):
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0)
        self._oval = self.create_oval(1, 1, size - 1, size - 1, fill=color, outline="")

    def set(self, color: str) -> None:
        self.itemconfigure(self._oval, fill=color)
