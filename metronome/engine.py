import queue

import numpy as np

from metronome.sound import make_click
from metronome.tempo import clamp_bpm


class Metronome:
    """Sample-accurate metronome.

    Clicks are mixed into the audio stream at exact sample offsets inside the
    output callback, so timing never depends on GUI or thread scheduling.
    Each beat is reported on ``beats`` as ``(beat_in_bar, stream_time)``,
    where ``stream_time`` is when the click reaches the speakers.
    """

    def __init__(self, bpm: int = 120, beats_per_bar: int = 4, samplerate: int = 44100):
        self.samplerate = samplerate
        self.bpm = bpm
        self.beats_per_bar = beats_per_bar
        self.click = make_click(1000, samplerate, volume=0.45)
        self.accent = make_click(1500, samplerate, volume=0.6)
        self.beats: queue.SimpleQueue[tuple[int, float]] = queue.SimpleQueue()
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

    def reset(self) -> None:
        self._next_beat = 0.0  # position of next beat, in samples from current block start
        self._beat_in_bar = 0
        self._tails: list[np.ndarray] = []  # unplayed ends of clicks that crossed a block

    def render(self, frames: int, start_time: float = 0.0) -> np.ndarray:
        """Produce the next ``frames`` mono samples and advance the beat clock."""
        out = np.zeros(frames, dtype=np.float32)
        tails = []
        for buf in self._tails:
            n = min(len(buf), frames)
            out[:n] += buf[:n]
            if len(buf) > n:
                tails.append(buf[n:])

        interval = self.samplerate * 60.0 / self.bpm
        bpb = max(1, self.beats_per_bar)
        while self._next_beat < frames:
            pos = int(self._next_beat)
            idx = self._beat_in_bar if self._beat_in_bar < bpb else 0
            buf = self.accent if idx == 0 else self.click
            n = min(len(buf), frames - pos)
            out[pos : pos + n] += buf[:n]
            if len(buf) > n:
                tails.append(buf[n:])
            self.beats.put((idx, start_time + pos / self.samplerate))
            self._beat_in_bar = idx + 1
            self._next_beat += interval

        self._next_beat -= frames
        self._tails = tails
        return out

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
