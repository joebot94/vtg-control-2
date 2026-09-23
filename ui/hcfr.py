from tkinter import ttk


class HCFRPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        ttk.Label(self, text="HCFRPage — not built yet", style="Dim.TLabel").pack()

    def refresh_from_device(self): pass
    def refresh_temperature(self): pass
