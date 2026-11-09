from metronome.tempo import TapTempo, clamp_bpm


def test_identical_timestamps_return_none():
    t = TapTempo()
    assert t.tap(1.0) is None
    assert t.tap(1.0) is None
    assert t.tap(1.0) is None


def test_recovers_after_identical_timestamps():
    t = TapTempo()
    t.tap(1.0)
    t.tap(1.0)
    assert t.tap(1.5) is not None


def test_very_fast_taps_clamp_to_max():
    t = TapTempo()
    t.tap(0.0)
    assert t.tap(0.01) == 300


def test_very_slow_taps_clamp_to_min():
    t = TapTempo(timeout=10.0)
    t.tap(0.0)
    assert t.tap(5.0) == 30


def test_gap_exactly_timeout_does_not_reset():
    t = TapTempo(timeout=2.0)
    t.tap(0.0)
    assert t.tap(2.0) == 30


def test_gap_after_timeout_restarts():
    t = TapTempo(timeout=2.0)
    t.tap(0.0)
    t.tap(0.5)
    assert t.tap(10.0) is None


def test_uses_injected_clock():
    ticks = iter([0.0, 0.5])
    t = TapTempo(clock=lambda: next(ticks))
    t.tap()
    assert t.tap() == 120


def test_backwards_timestamp_returns_none():
    t = TapTempo()
    t.tap(5.0)
    assert t.tap(4.0) is None


def test_clamp_bpm_edges():
    assert clamp_bpm(29.5) == 30
    assert clamp_bpm(300.4) == 300
    assert clamp_bpm(-5) == 30
    assert clamp_bpm(float("inf")) == 300
