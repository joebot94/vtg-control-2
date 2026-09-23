"""JOEBOT VTG — Extron VTG 400 controller.

    python main.py              run the app
    python main.py --selftest   build the whole UI against MOCK, write
                                selftest.txt next to the app, exit 0/1
                                (CI runs this on the built Windows exe)
"""

import sys


def selftest() -> int:
    import tkinter as tk
    import traceback

    from vtg import hcfr
    from vtg.paths import app_dir

    report = app_dir() / "selftest.txt"
    try:
        from ui.main import App

        root = tk.Tk()
        app = App(root)
        app.connect()  # MOCK is the default port
        for _ in range(40):
            root.update()
            root.after(25)
        model = app.model
        lines = [
            "OK",
            f"model: {model}",
            f"tabs: {[app.notebook.tab(i, 'text') for i in app.notebook.tabs()]}",
            f"presets: {len(app.presets._paths)}",
            f"hcfr: {hcfr.unavailable_reason() or 'available'}",
        ]
        app.quit()
        ok = model == "VTG 400"
    except Exception:  # noqa: BLE001
        lines, ok = ["FAIL", traceback.format_exc()], False
    report.write_text("\n".join(lines if ok else ["FAIL"] + lines[1:]) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from ui.main import run

    run()
