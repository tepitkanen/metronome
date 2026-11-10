import queue
from typing import NamedTuple

import numpy as np

from metronome.sound import ACCENT, MUTE, NORMAL, SOUNDS, SUB
from metronome.tempo import clamp_bpm

SUBDIVISIONS = (1, 2, 3, 4)  # quarter, eighths, triplets, sixteenths
MIN_SWING = 0.5  # offbeat eighth exactly halfway: straight
MAX_SWING = 0.75  # offbeat on the last sixteenth: hard swing


class Beat(NamedTuple):
    """One main beat, as reported to the GUI (subdivision ticks are not reported)."""

    beat_in_bar: int  # position in the bar, 0 = downbeat
    time: float  # stream time at which the click reaches the speakers
    level: int  # ACCENT, NORMAL or MUTE
    audible: bool  # False inside a muted gap-trainer bar
    bpm: int  # tempo of this beat
    bumped: bool = False  # True when the speed trainer raised the tempo on this beat


class Metronome:
    """Sample-accurate metronome.

    Clicks are mixed into the audio stream at exact sample offsets inside the
    output callback, so timing never depends on GUI or thread scheduling.
    Settings are plain attributes read once per block; lists, tuples and dicts
    are always replaced rather than mutated, so no locking is needed.
    """

    def __init__(
        self,
        bpm: int = 120,
        beats_per_bar: int = 4,
        samplerate: int = 44100,
        sound: str = "Beep",
    ):
        self.samplerate = samplerate
        self.bpm = bpm
        self.beats_per_bar = beats_per_bar
        self.subdivision = 1
        self.swing = MIN_SWING
        self.accents: list[int] = []  # per-beat levels; missing beats use default_level()
        self.volume = 1.0
        self.gap_bars: tuple[int, int] | None = None  # (bars on, bars muted)
        self.speed: tuple[int, int, int] | None = None  # (+bpm, every n bars, target bpm)
        self.buffers: dict[int, np.ndarray] = {}
        self.set_sound(sound)
        self.beats: queue.SimpleQueue[Beat] = queue.SimpleQueue()
        self._stream = None
        self.reset()

    @property
    def bpm(self) -> int:
        return self._bpm

    @bpm.setter
    def bpm(self, value: float) -> None:
        self._bpm = clamp_bpm(value)

    @property
    def running(self) -> bool:
        return self._stream is not None

    def set_sound(self, name: str) -> None:
        self.buffers = SOUNDS[name](self.samplerate)

    @staticmethod
    def default_level(beat: int) -> int:
        return ACCENT if beat == 0 else NORMAL

    def level_of(self, beat: int) -> int:
        accents = self.accents
        return accents[beat] if beat < len(accents) else self.default_level(beat)

    def reset(self) -> None:
        self._beat_start = 0.0  # current beat's position, in samples from block start
        self._beat_interval = 0.0  # latched when the beat starts
        self._tick = 0  # next subdivision tick within the current beat
        self._beat_in_bar = 0  # index the next beat will get
        self._bar = -1  # bars since start; becomes 0 on the first downbeat
        self._beat_sounds = True  # whether the current beat (and its subs) is heard
        self._tails: list[np.ndarray] = []  # unplayed ends of clicks that crossed a block

    def _start_beat(self, bpb: int) -> Beat:
        """Advance bar/beat counters for a new beat and apply the trainers."""
        idx = self._beat_in_bar if self._beat_in_bar < bpb else 0
        bumped = False
        if idx == 0:
            self._bar += 1
            speed = self.speed
            if speed is not None and self._bar > 0 and self._bar % max(1, speed[1]) == 0:
                step, _, target = speed
                if self.bpm < target:
                    self.bpm = min(target, self.bpm + step)
                    bumped = True
        self._beat_interval = self.samplerate * 60.0 / self.bpm
        self._beat_in_bar = idx + 1

        gap = self.gap_bars
        audible = gap is None or self._bar % max(1, gap[0] + gap[1]) < gap[0]
        level = self.level_of(idx)
        self._beat_sounds = audible and level != MUTE
        return Beat(idx, 0.0, level, audible, self.bpm, bumped)

    def render(self, frames: int, start_time: float = 0.0) -> np.ndarray:
        """Produce the next ``frames`` mono samples and advance the beat clock."""
        out = np.zeros(frames, dtype=np.float32)
        tails = []
        for buf in self._tails:
            self._mix(out, tails, buf, 0)

        sub = self.subdivision if self.subdivision in SUBDIVISIONS else 1
        swing = min(MAX_SWING, max(MIN_SWING, self.swing))
        bpb = max(1, self.beats_per_bar)
        buffers = self.buffers
        while True:
            if self._tick >= sub:  # beat finished (also if subdivision just shrank)
                self._beat_start += self._beat_interval
                self._tick = 0
            if self._tick == 0:
                pos_f = self._beat_start
            else:
                frac = swing if sub == 2 else self._tick / sub
                pos_f = self._beat_start + self._beat_interval * frac
            if pos_f >= frames:
                break
            if pos_f < 0:  # tick made late by a subdivision/swing change: skip it
                self._tick += 1
                continue
            pos = int(pos_f)
            if self._tick == 0:
                beat = self._start_beat(bpb)
                self.beats.put(beat._replace(time=start_time + pos / self.samplerate))
                key = beat.level
            else:
                key = SUB
            if self._beat_sounds:
                self._mix(out, tails, buffers[key], pos)
            self._tick += 1

        self._beat_start -= frames
        self._tails = tails
        if self.volume != 1.0:
            out *= max(0.0, self.volume)
        np.clip(out, -1.0, 1.0, out=out)
        return out

    @staticmethod
    def _mix(out: np.ndarray, tails: list[np.ndarray], buf: np.ndarray, pos: int) -> None:
        n = min(len(buf), len(out) - pos)
        out[pos : pos + n] += buf[:n]
        if len(buf) > n:
            tails.append(buf[n:])

    def _callback(self, outdata, frames, time, status) -> None:
        start = time.outputBufferDacTime or time.currentTime
        outdata[:, 0] = self.render(frames, start)

    def start(self) -> None:
        if self.running:
            return
        import sounddevice as sd

        self.reset()
        stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        try:
            stream.start()
        except BaseException:
            stream.close()  # don't leak the opened PortAudio stream
            raise
        self._stream = stream

    def stop(self) -> None:
        if self._stream is None:
            return
        stream, self._stream = self._stream, None
        try:
            stream.stop()
        finally:
            stream.close()

    def stream_time(self) -> float | None:
        """Current time on the stream's clock, or None when stopped."""
        return self._stream.time if self._stream is not None else None
