import numpy as np


def make_click(
    freq: float, samplerate: int, ms: float = 30.0, volume: float = 0.5
) -> np.ndarray:
    """Return a short decaying sine burst as a mono float32 array."""
    n = int(samplerate * ms / 1000)
    t = np.arange(n) / samplerate
    envelope = np.exp(-t * 150.0)
    fade_in = min(n, max(1, samplerate // 2000))  # ~0.5 ms, avoids a pop at onset
    envelope[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    return (volume * envelope * np.sin(2 * np.pi * freq * t)).astype(np.float32)
