import queue
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

import sounddevice as sd

from metronome.engine import MAX_SWING, MIN_SWING, Beat, Metronome
from metronome.sound import ACCENT, MUTE, NORMAL, SOUNDS
from metronome.tempo import MAX_BPM, MIN_BPM, TapTempo, clamp_bpm, tempo_name

POLL_MS = 10
DOT_SIZE = 40
DOT_GAP = 12
FONT = "Segoe UI"
COLOR_MUTED_TEXT = "#777777"
COLOR_IDLE = "#d0d0d0"
COLOR_IDLE_ACCENT = "#f3b4b4"
COLOR_OUTLINE_MUTE = "#999999"
COLOR_BEAT = "#3b82f6"
COLOR_ACCENT = "#ef4444"
COLOR_SILENT = "#c7d2fe"  # lit beat that makes no sound (muted beat / gap bar)

SUBDIVISION_NAMES = {"Quarter notes": 1, "Eighths": 2, "Triplets": 3, "Sixteenths": 4}
NEXT_LEVEL = {ACCENT: NORMAL, NORMAL: MUTE, MUTE: ACCENT}


class IntField:
    """An integer Spinbox value: applied live while valid, clamped when the field is left."""

    def __init__(self, var: tk.IntVar, lo: int, hi: int, apply: Callable[[int], None]):
        self.var, self.lo, self.hi, self.apply = var, lo, hi, apply
        self.last = var.get()  # last valid value, restored when the text is invalid
        var.trace_add("write", lambda *_: self._on_write())

    def read(self) -> int | None:
        try:
            return self.var.get()
        except tk.TclError:  # partially typed / empty field
            return None

    def _on_write(self) -> None:
        value = self.read()
        # Ignore out-of-range values while typing (e.g. "5" on the way to "50");
        # commit() clamps them when the field is left.
        if value is not None and self.lo <= value <= self.hi:
            self.last = value
            self.apply(value)

    def commit(self) -> None:
        value = self.read()
        fixed = self.last if value is None else max(self.lo, min(self.hi, value))
        if fixed != value:
            self.var.set(fixed)  # triggers _on_write, which applies it


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=16)
        self.root = root
        self.engine = Metronome()
        self.tapper = TapTempo()
        self._pending: list[Beat] = []
        self._fields: list[IntField] = []
        self._base_bpm = self.engine.bpm  # last tempo the user set; Stop returns to it
        self._showing_bump = False  # True while mirroring a speed-trainer bump into bpm_var

        self.bpm_var = tk.IntVar(value=self.engine.bpm)
        self.bpb_var = tk.IntVar(value=self.engine.beats_per_bar)
        self._field(self.bpm_var, MIN_BPM, MAX_BPM, self._set_bpm)
        self._field(self.bpb_var, 1, 12, self._set_bpb)

        self.sub_var = tk.StringVar(value="Quarter notes")
        self.swing_var = tk.IntVar(value=round(MIN_SWING * 100))
        self.sound_var = tk.StringVar(value="Beep")
        self.volume_var = tk.IntVar(value=round(self.engine.volume * 100))

        self.gap_on = tk.BooleanVar(value=False)
        self.gap_play = tk.IntVar(value=2)
        self.gap_mute = tk.IntVar(value=2)
        self.speed_on = tk.BooleanVar(value=False)
        self.speed_step = tk.IntVar(value=5)
        self.speed_every = tk.IntVar(value=4)
        self.speed_target = tk.IntVar(value=160)
        for var, lo, hi in (
            (self.gap_play, 1, 16),
            (self.gap_mute, 1, 16),
            (self.speed_step, 1, 50),
            (self.speed_every, 1, 32),
            (self.speed_target, MIN_BPM, MAX_BPM),
        ):
            self._field(var, lo, hi, lambda _v: self.apply_trainers())

        self._build()
        self._bind_keys()
        self._draw_dots()
        self.after(POLL_MS, self._poll_beats)

    def _field(self, var: tk.IntVar, lo: int, hi: int, apply: Callable[[int], None]) -> None:
        self._fields.append(IntField(var, lo, hi, apply))

    # --- layout -------------------------------------------------------------

    def _build(self) -> None:
        self.grid(sticky="nsew")
        self.columnconfigure(1, weight=1)

        style = ttk.Style(self.root)
        style.configure("Nudge.TButton", font=(FONT, 16), padding=(4, 6))
        style.configure("Primary.TButton", font=(FONT, 14, "bold"), padding=(0, 10))

        bpm_entry = self._build_hero(row=0)
        ttk.Scale(
            self,
            from_=MIN_BPM,
            to=MAX_BPM,
            orient="horizontal",
            command=lambda v: self.bpm_var.set(clamp_bpm(float(v))),
            variable=self.bpm_var,
            takefocus=False,
        ).grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(
            self, text="Tap", command=self.tap, takefocus=False, width=6
        ).grid(row=1, column=2, padx=(8, 0))

        # Sized to fit the dots exactly (see _draw_dots) and left unstretched, so it centers.
        self.canvas = tk.Canvas(self, height=DOT_SIZE + 4, highlightthickness=0)
        self.canvas.grid(row=2, column=0, columnspan=3, pady=(20, 16))

        self.start_btn = ttk.Button(
            self, text="Start", command=self.toggle, takefocus=False,
            style="Primary.TButton",
        )
        self.start_btn.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        # Live trainer status; an empty label keeps its line, so nothing jumps while running.
        self.status_label = ttk.Label(self, foreground=COLOR_MUTED_TEXT)
        self.status_label.grid(row=4, column=0, columnspan=3, pady=(0, 4))

        ttk.Label(self, text="Beats per bar").grid(row=5, column=0, sticky="w", pady=(8, 0))
        bpb_spin = ttk.Spinbox(self, from_=1, to=12, textvariable=self.bpb_var, width=5)
        bpb_spin.grid(row=5, column=2, padx=(8, 0), pady=(8, 0))

        ttk.Label(self, text="Subdivision").grid(row=6, column=0, sticky="w", pady=(8, 0))
        sub_box = ttk.Combobox(
            self, textvariable=self.sub_var, values=list(SUBDIVISION_NAMES),
            state="readonly", width=14,
        )
        sub_box.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        sub_box.bind("<<ComboboxSelected>>", lambda e: self.set_subdivision())

        ttk.Label(self, text="Swing").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.swing_scale = ttk.Scale(
            self,
            from_=round(MIN_SWING * 100),
            to=round(MAX_SWING * 100),
            orient="horizontal",
            variable=self.swing_var,
            command=lambda v: self.set_swing(round(float(v))),
            takefocus=False,
        )
        self.swing_scale.grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.swing_label = ttk.Label(self, width=5)
        self.swing_label.grid(row=7, column=2, padx=(8, 0), pady=(8, 0))

        self._build_sound(row=8)
        spins = [bpm_entry, bpb_spin, *self._build_practice(row=9)]

        ttk.Label(
            self,
            text="Space start/stop · ↑/↓ or scroll ±1 · Shift+↑/↓ ±10 · T tap\n"
            "Click a dot to cycle accent → normal → mute",
            foreground=COLOR_MUTED_TEXT,
            justify="center",
        ).grid(row=10, column=0, columnspan=3, pady=(12, 0))

        # Return/Escape in a spinbox hands focus back so shortcuts work again;
        # leaving the field shows the value actually in use.
        for spin in spins:
            spin.bind("<Return>", lambda e: self.root.focus_set())
            spin.bind("<Escape>", lambda e: self.root.focus_set())
            spin.bind("<FocusOut>", lambda e: self.commit_fields())
            spin.bind("<space>", self._space_in_field)
        self.canvas.bind("<Button-1>", self._on_dot_click)

        self.set_subdivision()
        self.set_swing(self.swing_var.get())
        self.set_volume(self.volume_var.get())  # also fills the section summaries

    def _section(self, row: int, title: str) -> tuple[ttk.Frame, ttk.Label]:
        """A collapsible section (starts collapsed): header toggle + summary, and a body."""
        section = ttk.Frame(self)
        section.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        section.columnconfigure(1, weight=1)
        body = ttk.Frame(section, padding=(12, 4, 0, 0))
        body.grid(row=1, column=0, columnspan=2, sticky="ew")
        body.grid_remove()

        def toggle() -> None:
            shown = body.winfo_manager() == "grid"
            if shown:
                body.grid_remove()
            else:
                body.grid()
            button.configure(text=f"{'▸' if shown else '▾'} {title}")

        button = ttk.Button(
            section, text=f"▸ {title}", command=toggle, takefocus=False, style="Toolbutton"
        )
        button.grid(row=0, column=0, sticky="w")
        summary = ttk.Label(section, foreground=COLOR_MUTED_TEXT)
        summary.grid(row=0, column=1, sticky="e")
        return body, summary

    def _build_sound(self, row: int) -> None:
        body, self.sound_summary = self._section(row, "Sound")
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Sound").grid(row=0, column=0, sticky="w")
        sound_box = ttk.Combobox(
            body, textvariable=self.sound_var, values=list(SOUNDS),
            state="readonly", width=14,
        )
        sound_box.grid(row=0, column=1, sticky="w", padx=(8, 0))
        sound_box.bind("<<ComboboxSelected>>", lambda e: self.set_sound())

        ttk.Label(body, text="Volume").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            body,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.volume_var,
            command=lambda v: self.set_volume(round(float(v))),
            takefocus=False,
        ).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.volume_label = ttk.Label(body, width=5)
        self.volume_label.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

    def _build_hero(self, row: int) -> ttk.Entry:
        """The tempo display: marking, big editable BPM number and -/+ buttons."""
        hero = ttk.Frame(self)
        hero.grid(row=row, column=0, columnspan=3, pady=(0, 8))
        self.tempo_label = ttk.Label(
            hero, text=tempo_name(self.engine.bpm), font=(FONT, 12),
            foreground=COLOR_MUTED_TEXT,
        )
        self.tempo_label.grid(row=0, column=0, columnspan=3)
        for column, delta, text in ((0, -1, "−"), (2, 1, "+")):
            ttk.Button(
                hero, text=text, width=3, style="Nudge.TButton", takefocus=False,
                command=lambda d=delta: self.nudge(d),
            ).grid(row=1, column=column)
        entry = ttk.Entry(
            hero, textvariable=self.bpm_var, width=3, justify="center",
            font=(FONT, 48, "bold"),
        )
        entry.grid(row=1, column=1, padx=12)
        ttk.Label(hero, text="BPM", foreground=COLOR_MUTED_TEXT).grid(
            row=2, column=0, columnspan=3
        )
        for widget in (hero, *hero.winfo_children()):
            widget.bind("<MouseWheel>", self._on_wheel)
        return entry

    def _on_wheel(self, event) -> str:
        self.commit_fields()  # a half-typed number snaps back before nudging
        self.nudge(1 if event.delta > 0 else -1)
        return "break"

    def _build_practice(self, row: int) -> list[ttk.Spinbox]:
        frame, self.practice_summary = self._section(row, "Practice")

        def spin(var, lo, hi, column, r):
            s = ttk.Spinbox(frame, from_=lo, to=hi, textvariable=var, width=4)
            s.grid(row=r, column=column, padx=2)
            return s

        def label(text, column, r):
            ttk.Label(frame, text=text).grid(row=r, column=column, sticky="w")

        ttk.Checkbutton(
            frame, text="Gap trainer", variable=self.gap_on,
            command=self.apply_trainers, takefocus=False,
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        label("play", 1, 0)
        s1 = spin(self.gap_play, 1, 16, 2, 0)
        label("bars, mute", 3, 0)
        s2 = spin(self.gap_mute, 1, 16, 4, 0)
        label("bars", 5, 0)

        ttk.Checkbutton(
            frame, text="Speed trainer", variable=self.speed_on,
            command=self.apply_trainers, takefocus=False,
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        label("+", 1, 1)
        s3 = spin(self.speed_step, 1, 50, 2, 1)
        label("BPM every", 3, 1)
        s4 = spin(self.speed_every, 1, 32, 4, 1)
        label("bars, up to", 5, 1)
        s5 = spin(self.speed_target, MIN_BPM, MAX_BPM, 6, 1)
        return [s1, s2, s3, s4, s5]

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

    def _space_in_field(self, _event) -> str:
        """A number never contains a space, so Space in a field commits it and starts/stops."""
        self.commit_fields()
        self.root.focus_set()
        self.toggle()
        return "break"  # don't let the Entry insert the space

    def _unless_typing(self, handler):
        """Skip shortcuts while a text field has focus, so typing works normally."""

        def wrapped(event):
            if isinstance(event.widget, (tk.Entry, ttk.Entry)):  # incl. Spinbox, Combobox
                return None
            handler(event)
            return "break"

        return wrapped

    # --- beat dots ----------------------------------------------------------

    def _draw_dots(self, active: Beat | None = None) -> None:
        self.canvas.delete("all")
        n = self.engine.beats_per_bar
        self.canvas.configure(width=4 + n * DOT_SIZE + (n - 1) * DOT_GAP)
        for i in range(n):
            level = self.engine.level_of(i)
            x = 2 + i * (DOT_SIZE + DOT_GAP)
            outline = COLOR_OUTLINE_MUTE if level == MUTE else ""
            if active is not None and i == active.beat_in_bar:
                if not active.audible or level == MUTE:
                    fill = COLOR_SILENT
                else:
                    fill = COLOR_ACCENT if level == ACCENT else COLOR_BEAT
            else:
                fill = {ACCENT: COLOR_IDLE_ACCENT, NORMAL: COLOR_IDLE, MUTE: ""}[level]
            self.canvas.create_oval(
                x, 2, x + DOT_SIZE, 2 + DOT_SIZE, fill=fill, outline=outline, width=2
            )

    def _dot_at(self, x: int) -> int | None:
        i, offset = divmod(x - 2, DOT_SIZE + DOT_GAP)
        if 0 <= i < self.engine.beats_per_bar and offset <= DOT_SIZE:
            return i
        return None

    def _on_dot_click(self, event) -> None:
        self.root.focus_set()
        i = self._dot_at(event.x)
        if i is not None:
            self.cycle_accent(i)

    def cycle_accent(self, beat: int) -> None:
        # Cover every visible beat, and keep levels beyond it in case beats per bar grows again.
        n = max(self.engine.beats_per_bar, len(self.engine.accents))
        levels = [self.engine.level_of(i) for i in range(n)]
        levels[beat] = NEXT_LEVEL[levels[beat]]
        self.engine.accents = levels  # replaced, never mutated (read by the audio thread)
        self._draw_dots()

    def _poll_beats(self) -> None:
        while True:
            try:
                self._pending.append(self.engine.beats.get_nowait())
            except queue.Empty:
                break
        now = self.engine.stream_time()
        if now is not None:
            due = [b for b in self._pending if b.time <= now]
            if due:
                self._pending = self._pending[len(due) :]
                if any(b.bumped for b in due):  # speed trainer changed the tempo
                    self._showing_bump = True
                    try:
                        self.bpm_var.set(due[-1].bpm)
                    finally:
                        self._showing_bump = False
                self._draw_dots(active=due[-1])
                self._show_status(due[-1])
        self.after(POLL_MS, self._poll_beats)

    def _show_status(self, beat: Beat) -> None:
        """Trainer status from the latest due beat; empty when no trainer is on."""
        parts = []
        if self.engine.gap_bars is not None:
            parts.append("Playing" if beat.audible else "Silent bar")
        if self.engine.speed is not None:
            parts.append(f"{beat.bpm} → {self.engine.speed[2]} BPM")
        self.status_label.configure(text=" · ".join(parts))

    # --- actions ------------------------------------------------------------

    def toggle(self) -> None:
        if self.engine.running:
            self.engine.stop()
            self.start_btn.configure(text="Start")
            self.status_label.configure(text="")
            self._pending.clear()
            if self.engine.bpm != self._base_bpm:  # undo the speed trainer's ramp
                self.bpm_var.set(self._base_bpm)
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
        """Clamp typed values into range; invalid text reverts to the last valid value."""
        for field in self._fields:
            field.commit()

    def _set_bpm(self, value: int) -> None:
        self.engine.bpm = value
        self.tempo_label.configure(text=tempo_name(value))
        if not self._showing_bump:
            self._base_bpm = self.engine.bpm

    def _set_bpb(self, value: int) -> None:
        self.engine.beats_per_bar = value
        self._draw_dots()

    def set_subdivision(self) -> None:
        sub = SUBDIVISION_NAMES.get(self.sub_var.get(), 1)
        self.engine.subdivision = sub
        self.swing_scale.state(["!disabled"] if sub == 2 else ["disabled"])
        self.root.focus_set()

    def set_swing(self, pct: int) -> None:
        self.swing_var.set(pct)
        self.engine.swing = pct / 100
        self.swing_label.configure(text=f"{pct}%")

    def set_sound(self) -> None:
        self.engine.set_sound(self.sound_var.get())
        self._update_summaries()
        self.root.focus_set()

    def set_volume(self, pct: int) -> None:
        self.volume_var.set(pct)
        self.engine.volume = pct / 100
        self.volume_label.configure(text=f"{pct}%")
        self._update_summaries()

    def _update_summaries(self) -> None:
        """Refresh the collapsed-section summaries from the settings in effect."""
        self.sound_summary.configure(
            text=f"{self.sound_var.get()} · {round(self.engine.volume * 100)}%"
        )
        parts = []
        if self.engine.gap_bars is not None:
            parts.append("Gap {}/{}".format(*self.engine.gap_bars))
        if self.engine.speed is not None:
            parts.append("Speed +{}/{} bars → {}".format(*self.engine.speed))
        self.practice_summary.configure(text=" · ".join(parts) or "Off")

    def apply_trainers(self) -> None:
        """Push the Practice settings to the engine (using each field's last valid value)."""
        def f(var: tk.IntVar) -> int:
            return next(field.last for field in self._fields if field.var is var)

        self.engine.gap_bars = (
            (f(self.gap_play), f(self.gap_mute)) if self.gap_on.get() else None
        )
        self.engine.speed = (
            (f(self.speed_step), f(self.speed_every), f(self.speed_target))
            if self.speed_on.get()
            else None
        )
        self._update_summaries()


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
