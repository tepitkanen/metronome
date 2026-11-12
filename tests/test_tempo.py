from metronome.tempo import MAX_BPM, MIN_BPM, TapTempo, clamp_bpm, tempo_name


def test_clamp_bpm():
    assert clamp_bpm(10) == MIN_BPM
    assert clamp_bpm(1000) == MAX_BPM
    assert clamp_bpm(120.4) == 120


def test_first_tap_returns_none():
    assert TapTempo().tap(0.0) is None


def test_tap_averages_intervals():
    t = TapTempo()
    for now in (0.0, 0.5, 1.0):
        bpm = t.tap(now)
    assert bpm == 120


def test_tap_keeps_only_recent_taps():
    t = TapTempo(max_taps=4)
    # Slow taps first, then four quick ones: only the quick ones should count.
    for now in (0.0, 1.0, 2.0, 2.25, 2.5, 2.75):
        bpm = t.tap(now)
    assert bpm == 240


def test_tap_resets_after_gap():
    t = TapTempo(timeout=2.0)
    t.tap(0.0)
    t.tap(0.5)
    assert t.tap(10.0) is None
    assert t.tap(11.0) == 60


def test_tempo_name_boundaries():
    assert tempo_name(MIN_BPM) == "Grave"
    assert tempo_name(39) == "Grave"
    assert tempo_name(40) == "Largo"
    assert tempo_name(119) == "Moderato"
    assert tempo_name(120) == "Allegro"
    assert tempo_name(MAX_BPM) == "Prestissimo"
