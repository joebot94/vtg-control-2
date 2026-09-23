"""Dev helper (macOS): launch the app, run a few UI steps, screenshot only
the app window, quit.  python tools/snap.py OUT.png [tab] [connect] [python-steps]"""

import subprocess
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui.main import App  # noqa: E402

out = sys.argv[1]
tab = int(sys.argv[2]) if len(sys.argv) > 2 else 0
connect = len(sys.argv) > 3 and sys.argv[3] == "connect"
steps = sys.argv[4] if len(sys.argv) > 4 else ""  # python run against `app` after connect

root = tk.Tk()
app = App(root)
root.lift()
root.attributes("-topmost", True)
if connect:
    root.after(200, app.connect)
root.after(400, lambda: app.notebook.select(tab))
if steps:
    root.after(900, lambda: exec(steps, {"app": app, "root": root}))


def shoot():
    root.update_idletasks()
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    subprocess.run(["screencapture", "-x", "-o", f"-R{x},{y},{w},{h}", out], check=True)
    app.quit()


root.after(3000, shoot)
root.mainloop()
