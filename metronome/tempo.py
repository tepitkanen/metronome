import time
from collections.abc import Callable

MIN_BPM = 30
MAX_BPM = 300


def clamp_bpm(bpm: float) -> int:
    # Clamp before rounding so inf/nan don't reach round() (nan maps to MIN_BPM).
    return round(min(MAX_BPM, max(MIN_BPM, bpm)))


class TapTempo:
    """Average the intervals between the most recent taps into a BPM."""

    def __init__(
        self,
        max_taps: int = 4,
        timeout: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_taps = max_taps
        self.timeout = timeout
        self.clock = clock
        self._taps: list[float] = []

    def tap(self, now: float | None = None) -> int | None:
        """Register a tap; return the BPM once there are at least two taps."""
        if now is None:
            now = self.clock()
        if self._taps and now - self._taps[-1] > self.timeout:
            self._taps.clear()
        self._taps.append(now)
        self._taps = self._taps[-self.max_taps :]
        if len(self._taps) < 2:
            return None
        interval = (self._taps[-1] - self._taps[0]) / (len(self._taps) - 1)
        if interval <= 0:
            return None
        return clamp_bpm(60.0 / interval)
