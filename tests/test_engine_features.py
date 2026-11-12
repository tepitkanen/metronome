"""Subdivisions, swing, accent patterns, volume, sounds and the practice trainers."""

import numpy as np
import pytest

from metronome.engine import Metronome
from metronome.sound import ACCENT, MUTE, NORMAL, SOUNDS, SUB

SR = 1000
ONE = 1  # stand-in click length: one sample, so onsets are easy to read


def make(bpm=60, bpb=4, sub=1):
    m = Metronome(bpm=bpm, beats_per_bar=bpb, samplerate=SR)
    m.buffers = {
        ACCENT: np.full(ONE, 1.0, dtype=np.float32),
        NORMAL: np.full(ONE, 0.5, dtype=np.float32),
        SUB: np.full(ONE, 0.25, dtype=np.float32),
    }
    m.subdivision = sub
    return m


def drain(m):
    out = []
    while not m.beats.empty():
        out.append(m.beats.get_nowait())
    return out


def onsets(signal):
    return {int(i): float(signal[i]) for i in np.flatnonzero(signal)}


# --- subdivisions & swing ----------------------------------------------------


@pytest.mark.parametrize(
    ("sub", "expected"),
    [
        (2, {0: 1.0, 500: 0.25, 1000: 0.5, 1500: 0.25}),
        (3, {0: 1.0, 333: 0.25, 666: 0.25, 1000: 0.5, 1333: 0.25, 1666: 0.25}),
        (4, {0: 1.0, 250: 0.25, 500: 0.25, 750: 0.25, 1000: 0.5, 1250: 0.25, 1500: 0.25, 1750: 0.25}),
    ],
)
def test_subdivision_tick_positions(sub, expected):
    m = make(bpm=60, sub=sub)  # beat every 1000 samples
    assert onsets(m.render(2000)) == expected


def test_subdivision_ticks_are_not_reported_as_beats():
    m = make(bpm=60, sub=4)
    m.render(2000)
    assert [b.beat_in_bar for b in drain(m)] == [0, 1]


def test_swing_delays_offbeat_eighth():
    m = make(bpm=60, sub=2)
    m.swing = 0.66
    assert onsets(m.render(2000)) == {0: 1.0, 660: 0.25, 1000: 0.5, 1660: 0.25}


def test_swing_delays_offbeat_sixteenths():
    m = make(bpm=60, sub=4)
    m.swing = 0.7
    assert onsets(m.render(1000)) == {0: 1.0, 350: 0.25, 500: 0.25, 850: 0.25}


def test_swing_is_clamped_and_ignored_for_other_subdivisions():
    m = make(bpm=60, sub=2)
    m.swing = 5.0
    assert 750 in onsets(m.render(1000))
    m = make(bpm=60, sub=3)
    m.swing = 0.7
    assert set(onsets(m.render(1000))) == {0, 333, 666}


def test_subdivision_change_mid_run_keeps_beat_grid():
    m = make(bpm=60, sub=4)
    a = m.render(1600)  # mid-beat 2, ticks at 1000, 1250, 1500 played
    m.subdivision = 1
    b = m.render(2400)
    beats = sorted(set(onsets(np.concatenate([a, b]))) & {0, 1000, 2000, 3000})
    assert beats == [0, 1000, 2000, 3000]
    assert [x for x in onsets(b) if x + 1600 not in (2000, 3000)] == []  # no stray subs


def test_long_run_with_subdivisions_does_not_drift():
    sr, bpm, block = 44100, 97, 512
    m = Metronome(bpm=bpm, samplerate=sr)
    m.subdivision = 3
    interval = sr * 60.0 / bpm
    times = []
    for i in range(3000):
        m.render(block, start_time=i * block / sr)
        times += [b.time for b in drain(m)]
    for k, t in enumerate(times):
        assert abs(t * sr - k * interval) < 1.0 + 1e-6


# --- accent pattern ----------------------------------------------------------


def test_default_accent_pattern():
    m = make(bpm=300, bpb=3)
    m.render(1000)
    assert [b.level for b in drain(m)] == [ACCENT, NORMAL, NORMAL, ACCENT, NORMAL]


def test_custom_accent_pattern_and_padding():
    m = make(bpm=300, bpb=4)
    m.accents = [NORMAL, ACCENT]  # beats 2 and 3 fall back to the default (NORMAL)
    out = m.render(800)
    assert [b.level for b in drain(m)] == [NORMAL, ACCENT, NORMAL, NORMAL]
    assert onsets(out) == {0: 0.5, 200: 1.0, 400: 0.5, 600: 0.5}


def test_muted_beat_is_silent_with_its_subdivisions_but_still_reported():
    m = make(bpm=60, bpb=2, sub=2)
    m.accents = [ACCENT, MUTE]
    out = m.render(2000)
    assert onsets(out) == {0: 1.0, 500: 0.25}
    assert [(b.beat_in_bar, b.level) for b in drain(m)] == [(0, ACCENT), (1, MUTE)]


# --- volume & sounds ---------------------------------------------------------


def test_volume_scales_output():
    m = make(bpm=60)
    m.volume = 0.5
    assert onsets(m.render(10)) == {0: 0.5}
    m = make(bpm=60)
    m.volume = 0.0
    assert not m.render(10).any()


@pytest.mark.parametrize("name", list(SOUNDS))
def test_every_sound_has_valid_buffers(name):
    bank = SOUNDS[name](44100)
    assert set(bank) == {ACCENT, NORMAL, SUB}
    for buf in bank.values():
        assert buf.dtype == np.float32
        assert buf.ndim == 1 and len(buf) > 0
        assert np.isfinite(buf).all()
        assert np.abs(buf).max() <= 1.0
        assert np.abs(buf).max() > 0.01


def test_set_sound_replaces_buffers():
    m = Metronome(samplerate=44100)
    before = m.buffers
    m.set_sound("Hi-hat")
    assert m.buffers is not before
    out = m.render(2000)
    assert np.abs(out).max() > 0


# --- gap trainer -------------------------------------------------------------


def test_gap_trainer_mutes_off_bars_but_reports_them():
    m = make(bpm=300, bpb=2)  # beat every 200, bar every 400
    m.gap_bars = (1, 2)  # 1 bar on, 2 bars off
    out = m.render(2400)  # 6 bars
    assert sorted(onsets(out)) == [0, 200, 1200, 1400]
    assert [b.audible for b in drain(m)] == [True, True, False, False, False, False] * 2


def test_gap_trainer_disabled_plays_everything():
    m = make(bpm=300, bpb=2)
    m.render(800)
    assert all(b.audible for b in drain(m))


# --- speed trainer -----------------------------------------------------------


def test_speed_trainer_bumps_every_n_bars_up_to_target():
    m = make(bpm=60, bpb=1)  # one beat per bar
    m.speed = (20, 2, 120)  # +20 BPM every 2 bars, stop at 120
    for _ in range(40):
        m.render(250)
    bpms = [b.bpm for b in drain(m)]
    assert bpms[:8] == [60, 60, 80, 80, 100, 100, 120, 120]
    assert set(bpms[6:]) == {120}
    assert m.bpm == 120


def test_speed_trainer_does_not_overshoot_or_lower_tempo():
    m = make(bpm=110, bpb=1)
    m.speed = (25, 1, 120)
    m.render(2000)
    assert [b.bpm for b in drain(m)][:3] == [110, 120, 120]
    m = make(bpm=200, bpb=1)
    m.speed = (10, 1, 120)  # already above target: leave it alone
    m.render(2000)
    assert {b.bpm for b in drain(m)} == {200}


def test_speed_trainer_change_applies_on_downbeat_timing():
    m = make(bpm=60, bpb=2)
    m.speed = (60, 1, 120)  # bar 1 jumps to 120 BPM
    m.render(4000, start_time=0.0)
    times = [b.time for b in drain(m)]
    # bar 0 at 60 BPM: 0.0, 1.0; bar 1 starts at 2.0 at 120 BPM: 2.0, 2.5; bar 2 at 3.0
    assert times[:5] == [0.0, 1.0, 2.0, 2.5, 3.0]
