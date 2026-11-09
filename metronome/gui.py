import queue
import tkinter as tk
from tkinter import messagebox, ttk

import sounddevice as sd

from metronome.engine import Metronome
from metronome.tempo import MAX_BPM, MIN_BPM, TapTempo, clamp_bpm

POLL_MS = 10
DOT_SIZE = 28
DOT_GAP = 8
COLOR_IDLE = "#d0d0d0"
COLOR_BEAT = "#3b82f6"
COLOR_ACCENT = "#ef4444"


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=16)
        self.root = root
        self.engine = Metronome()
        self.tapper = TapTempo()
        self._pending: list[tuple[int, float]] = []

        self.bpm_var = tk.IntVar(value=self.engine.bpm)
        self.bpb_var = tk.IntVar(value=self.engine.beats_per_bar)
        self.bpm_var.trace_add("write", self._on_bpm_change)
        self.bpb_var.trace_add("write", self._on_bpb_change)

        self._build()
        self._bind_keys()
        self._draw_dots()
        self.after(POLL_MS, self._poll_beats)

    # --- layout -------------------------------------------------------------

    def _build(self) -> None:
        self.grid(sticky="nsew")
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="BPM").grid(row=0, column=0, sticky="w")
        bpm_spin = ttk.Spinbox(
            self, from_=MIN_BPM, to=MAX_BPM, textvariable=self.bpm_var, width=5
        )
        bpm_spin.grid(row=0, column=2, padx=(8, 0))
        ttk.Scale(
            self,
            from_=MIN_BPM,
            to=MAX_BPM,
            orient="horizontal",
            command=lambda v: self.bpm_var.set(clamp_bpm(float(v))),
            variable=self.bpm_var,
            takefocus=False,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(self, text="Beats per bar").grid(row=1, column=0, sticky="w", pady=(8, 0))
        bpb_spin = ttk.Spinbox(self, from_=1, to=12, textvariable=self.bpb_var, width=5)
        bpb_spin.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        self.canvas = tk.Canvas(self, height=DOT_SIZE + 4, highlightthickness=0)
        self.canvas.grid(row=2, column=0, columnspan=3, sticky="ew", pady=12)

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, columnspan=3)
        self.start_btn = ttk.Button(
            buttons, text="Start", command=self.toggle, takefocus=False, width=10
        )
        self.start_btn.grid(row=0, column=0, padx=4)
        ttk.Button(
            buttons, text="Tap", command=self.tap, takefocus=False, width=10
        ).grid(row=0, column=1, padx=4)

        ttk.Label(
            self,
            text="Space start/stop · ↑/↓ ±1 · Shift+↑/↓ ±10 · T tap",
            foreground="#777",
        ).grid(row=4, column=0, columnspan=3, pady=(12, 0))

        # Return/Escape in a spinbox hands focus back so shortcuts work again;
        # leaving the field shows the value the engine actually uses.
        for spin in (bpm_spin, bpb_spin):
            spin.bind("<Return>", lambda e: self.root.focus_set())
            spin.bind("<Escape>", lambda e: self.root.focus_set())
            spin.bind("<FocusOut>", lambda e: self.commit_fields())
        self.canvas.bind("<Button-1>", lambda e: self.root.focus_set())

    def _bind_keys(self) -> None:
        bindings = {
            "<space>": lambda e: self.toggle(),
            "<Up>": lambda e: self.nudge(1),
            "<Down>": lambda e: self.nudge(-1),
            "<Shift-Up>": lambda e: self.nudge(10),
            "<Shift-Down>": lambda e: self.nudge(-10),
            "<t>": lambda e: self.tap(),
            "<T>": lambda e: self.tap(),
        }
        for seq, handler in bindings.items():
            self.root.bind(seq, self._unless_typing(handler))

    def _unless_typing(self, handler):
        """Skip shortcuts while a text field has focus, so typing works normally."""

        def wrapped(event):
            if isinstance(event.widget, (tk.Entry, ttk.Entry)):
                return None
            handler(event)
            return "break"

        return wrapped

    # --- beat dots ----------------------------------------------------------

    def _draw_dots(self, active: int | None = None) -> None:
        self.canvas.delete("all")
        for i in range(self.engine.beats_per_bar):
            x = 2 + i * (DOT_SIZE + DOT_GAP)
            if i == active:
                color = COLOR_ACCENT if i == 0 else COLOR_BEAT
            else:
                color = COLOR_IDLE
            self.canvas.create_oval(x, 2, x + DOT_SIZE, 2 + DOT_SIZE, fill=color, outline="")

    def _poll_beats(self) -> None:
        while True:
            try:
                self._pending.append(self.engine.beats.get_nowait())
            except queue.Empty:
                break
        now = self.engine.stream_time()
        if now is not None:
            due = [b for b in self._pending if b[1] <= now]
            if due:
                self._pending = self._pending[len(due) :]
                self._draw_dots(active=due[-1][0])
        self.after(POLL_MS, self._poll_beats)

    # --- actions ------------------------------------------------------------

    def toggle(self) -> None:
        if self.engine.running:
            self.engine.stop()
            self.start_btn.configure(text="Start")
            self._pending.clear()
            self._draw_dots()
            return
        while not self.engine.beats.empty():
            self.engine.beats.get_nowait()
        self._pending.clear()
        try:
            self.engine.start()
        except (sd.PortAudioError, ValueError) as exc:  # no device, bad params, driver error
            messagebox.showerror("Audio error", f"Could not open audio output:\n{exc}")
            return
        self.start_btn.configure(text="Stop")

    def nudge(self, delta: int) -> None:
        self.bpm_var.set(clamp_bpm(self.engine.bpm + delta))

    def tap(self) -> None:
        bpm = self.tapper.tap()
        if bpm is not None:
            self.bpm_var.set(bpm)

    def commit_fields(self) -> None:
        """Clamp typed values into range and show what the engine actually uses.

        Invalid text (empty, "abc") reverts to the current engine value.
        """
        bpm = self._var_int(self.bpm_var)
        if bpm is not None:
            self.engine.bpm = bpm  # setter clamps
        if bpm != self.engine.bpm:
            self.bpm_var.set(self.engine.bpm)
        if self._var_int(self.bpb_var) != self.engine.beats_per_bar:
            self.bpb_var.set(self.engine.beats_per_bar)

    @staticmethod
    def _var_int(var: tk.IntVar) -> int | None:
        try:
            return var.get()
        except tk.TclError:  # partially typed / empty field
            return None

    def _on_bpm_change(self, *_) -> None:
        value = self._var_int(self.bpm_var)
        # Ignore out-of-range values while typing (e.g. "5" on the way to "50");
        # commit_fields() clamps them when the field is left.
        if value is not None and MIN_BPM <= value <= MAX_BPM:
            self.engine.bpm = value

    def _on_bpb_change(self, *_) -> None:
        try:
            value = self.bpb_var.get()
        except tk.TclError:
            return
        self.engine.beats_per_bar = max(1, min(12, value))
        self._draw_dots()


def main() -> None:
    root = tk.Tk()
    root.title("Metronome")
    root.resizable(False, False)
    app = App(root)

    def on_close():
        try:
            app.engine.stop()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
