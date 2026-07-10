import tkinter as tk

class Stopwatch:
    def __init__(self, root):
        self.root = root

        if isinstance(root, tk.Tk):
            self.root.title("Stopwatch")
            self.root.resizable(False, False)
            root.configure(bg="#1e1e2e")

        self.elapsed = 0        # total milliseconds elapsed
        self.running = False
        self.after_id = None

        # --- Display ---
        self.display_var = tk.StringVar(value="00:00:00.0")
        display = tk.Label(
            root,
            textvariable=self.display_var,
            font=("Courier", 48, "bold"),
            bg="#1e1e2e",
            fg="#cdd6f4",
            padx=30,
            pady=20,
        )
        display.pack()

        # --- Buttons ---
        btn_frame = tk.Frame(root, bg="#1e1e2e", pady=15)
        btn_frame.pack()

        btn_style = dict(font=("Helvetica", 14, "bold"), width=8, bd=0, cursor="hand2")

        self.start_btn = tk.Button(
            btn_frame, text="Start", bg="#a6e3a1", fg="#1e1e2e",
            command=self.start, **btn_style
        )
        self.start_btn.grid(row=0, column=0, padx=8)

        self.stop_btn = tk.Button(
            btn_frame, text="Stop", bg="#f38ba8", fg="#1e1e2e",
            command=self.stop, state="disabled", **btn_style
        )
        self.stop_btn.grid(row=0, column=1, padx=8)

        self.reset_btn = tk.Button(
            btn_frame, text="Reset", bg="#89b4fa", fg="#1e1e2e",
            command=self.reset, **btn_style
        )
        self.reset_btn.grid(row=0, column=2, padx=8)

        root.configure(bg="#1e1e2e")

    # ------------------------------------------------------------------ #
    def _format(self, ms):
        """Convert milliseconds → HH:MM:SS.d"""
        total_tenths = ms // 100
        tenths = total_tenths % 10
        total_seconds = ms // 1000
        seconds = total_seconds % 60
        minutes = (total_seconds // 60) % 60
        hours = total_seconds // 3600
        return f"{hours:02}:{minutes:02}:{seconds:02}.{tenths}"

    def _tick(self):
        """Called every 100 ms while running."""
        self.elapsed += 100
        self.display_var.set(self._format(self.elapsed))
        self.after_id = self.root.after(100, self._tick)

    # ------------------------------------------------------------------ #
    def start(self):
        if not self.running:
            self.running = True
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self._tick()

    def stop(self):
        if self.running:
            self.running = False
            self.root.after_cancel(self.after_id)
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")

    def reset(self):
        self.stop()
        self.elapsed = 0
        self.display_var.set("00:00:00.0")


if __name__ == "__main__":
    root = tk.Tk()
    Stopwatch(root)
    root.mainloop()