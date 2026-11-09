from collections.abc import Callable

import numpy as np

# Beat levels (per-beat accent pattern) and buffer keys.
MUTE = 0
NORMAL = 1
ACCENT = 2
SUB = 3  # subdivision tick; only used as a buffer key


def make_click(
    freq: float,
    samplerate: int,
    ms: float = 30.0,
    volume: float = 0.5,
    decay: float = 150.0,
) -> np.ndarray:
    """Return a short decaying sine burst as a mono float32 array."""
    n = int(samplerate * ms / 1000)
    t = np.arange(n) / samplerate
    envelope = np.exp(-t * decay)
    fade_in = min(n, max(1, samplerate // 2000))  # ~0.5 ms, avoids a pop at onset
    envelope[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    return (volume * envelope * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def make_noise_burst(
    samplerate: int, ms: float = 40.0, volume: float = 0.5, decay: float = 120.0
) -> np.ndarray:
    """Return a decaying burst of bright (high-passed) noise, hi-hat style."""
    n = int(samplerate * ms / 1000)
    t = np.arange(n) / samplerate
    noise = np.random.default_rng(0).uniform(-1.0, 1.0, n)  # fixed seed: same sound every run
    bright = np.diff(noise, prepend=0.0) / 2  # first difference = crude high-pass, stays in [-1, 1]
    return (volume * np.exp(-t * decay) * bright).astype(np.float32)


def _wood(freq: float, samplerate: int, volume: float) -> np.ndarray:
    body = make_click(freq, samplerate, ms=25, volume=0.7 * volume, decay=250)
    ring = make_click(freq * 2.76, samplerate, ms=25, volume=0.3 * volume, decay=400)
    return body + ring


SoundBank = dict[int, np.ndarray]

SOUNDS: dict[str, Callable[[int], SoundBank]] = {
    "Beep": lambda sr: {
        ACCENT: make_click(1500, sr, volume=0.6),
        NORMAL: make_click(1000, sr, volume=0.45),
        SUB: make_click(1000, sr, volume=0.2),
    },
    "Wood": lambda sr: {
        ACCENT: _wood(1100, sr, 0.7),
        NORMAL: _wood(800, sr, 0.55),
        SUB: _wood(800, sr, 0.25),
    },
    "Hi-hat": lambda sr: {
        ACCENT: make_noise_burst(sr, ms=60, volume=0.6, decay=70),
        NORMAL: make_noise_burst(sr, volume=0.45),
        SUB: make_noise_burst(sr, ms=25, volume=0.25, decay=200),
    },
    "Click": lambda sr: {
        ACCENT: make_click(3500, sr, ms=4, volume=0.7, decay=900),
        NORMAL: make_click(2500, sr, ms=4, volume=0.55, decay=900),
        SUB: make_click(2500, sr, ms=3, volume=0.25, decay=900),
    },
}
