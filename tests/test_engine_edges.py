"""Edge cases for the v2 engine: drift, trainers combined, odd settings."""

import numpy as np
import pytest

from metronome.engine import Metronome
from metronome.sound import ACCENT, NORMAL
from tests.test_engine_features import drain, make, onsets

SR = 44100


def real(bpm=100, bpb=4):
    return Metronome(bpm=bpm, beats_per_bar=bpb, samplerate=SR)


def test_long_run_swing_and_sub_changes_keep_beat_grid():
    m = real(bpm=113)
    m.swing = 0.7
    interval = SR * 60.0 / 113
    times = []
    for i in range(20000):
        m.subdivision = (1, 2, 3, 4)[(i // 3) % 4]
        m.render(512, start_time=i * 512 / SR)
        times += [b.time for b in drain(m)]
    assert len(times) > 400
    for k, t in enumerate(times):
        assert abs(t * SR - k * interval) < 1.0 + 1e-6


def test_swing_offbeat_positions_over_many_beats():
    m = make(bpm=60, sub=2)
    m.swing = 0.6
    out = m.render(1000 * 50)
    subs = sorted(i for i, v in onsets(out).items() if v == 0.25)
    assert subs == [k * 1000 + 600 for k in range(50)]


def test_bpm_change_mid_beat_with_subdivisions_keeps_latched_interval():
    m = make(bpm=60, sub=2)
    a = m.render(300)  # beat 0 at 0, sub due at 500
    m.bpm = 120
    b = m.render(1300)
    ons = onsets(np.concatenate([a, b]))
    # current beat finishes at the old tempo (sub at 500, next beat at 1000),
    # then the new tempo (interval 500) applies
    assert sorted(ons)[:5] == [0, 500, 1000, 1250, 1500]


def test_sub_increase_after_tick_already_passed_does_not_write_in_the_past():
    m = make(bpm=60, sub=1)
    m.render(650)  # beat 0 played, 650 samples into the beat
    m.subdivision = 2  # the eighth at 500 is already in the past
    out = m.render(900)  # next beat at 350
    # Only the beat at 350 and its own sub at 850 may sound.
    assert set(onsets(out)) <= {350, 850}


def test_gap_and_speed_trainers_combined():
    m = make(bpm=60, bpb=2)
    m.gap_bars = (1, 1)
    m.speed = (10, 1, 90)
    for _ in range(200):
        m.render(100)
    beats = drain(m)
    per_bar = [beats[i : i + 2] for i in range(0, 14, 2)]
    assert [b[0].audible for b in per_bar] == [True, False] * 3 + [True]
    assert [b[0].bpm for b in per_bar] == [60, 70, 80, 90, 90, 90, 90]
    assert [b[0].bumped for b in per_bar] == [False, True, True, True, False, False, False]
    assert all(b.bpm == bar[0].bpm for bar in per_bar for b in bar)


def test_gap_follows_bar_counter_when_beats_per_bar_shrinks_mid_bar():
    m = make(bpm=300, bpb=4)
    m.gap_bars = (1, 1)
    m.render(500)  # beats 0,1,2 of bar 0
    m.beats_per_bar = 2
    m.render(1500)
    beats = drain(m)
    assert [(b.beat_in_bar, b.audible) for b in beats[:8]] == [
        (0, True), (1, True), (2, True), (0, False), (1, False), (0, True), (1, True), (0, False),
    ]


def test_speed_every_one_bpb_one_high_bpm_matches_expected_sequence():
    m = real(bpm=200, bpb=1)
    m.speed = (7, 1, 300)
    expected, bpm, t = [], 200, 0.0
    for k in range(60):
        if k > 0 and bpm < 300:
            bpm = min(300, bpm + 7)
        expected.append((bpm, t))
        t += SR * 60.0 / bpm
    got = []
    for i in range(1500):
        m.render(512, start_time=i * 512 / SR)
        got += drain(m)
    assert [b.bpm for b in got[:60]] == [e[0] for e in expected]
    for b, (_, start) in zip(got[:60], expected, strict=True):
        assert abs(b.time * SR - start) < 1.0 + 1e-6
    assert m.bpm == 300


def test_speed_target_equal_to_current_bpm_never_bumps():
    m = make(bpm=120, bpb=1)
    m.speed = (5, 1, 120)
    m.render(3000)
    beats = drain(m)
    assert beats
    assert {b.bpm for b in beats} == {120}
    assert not any(b.bumped for b in beats)


def test_speed_every_zero_is_treated_as_one():
    m = make(bpm=60, bpb=1)
    m.speed = (10, 0, 100)
    m.render(4000)
    assert [b.bpm for b in drain(m)][:3] == [60, 70, 80]


@pytest.mark.parametrize("n", [3, 8])
def test_accents_list_longer_or_shorter_than_bar(n):
    m = make(bpm=300, bpb=4)
    m.accents = [NORMAL, ACCENT, NORMAL, NORMAL, ACCENT, ACCENT, ACCENT, ACCENT][:n]
    m.render(1700)
    levels = [b.level for b in drain(m)]
    assert levels[:4] == [m.level_of(i) for i in range(4)]
    assert levels[4:8] == levels[:4]  # surplus entries are ignored, missing ones default


@pytest.mark.parametrize("bad", [0, 7, -1, 5])
def test_unknown_subdivision_falls_back_to_quarters(bad):
    m = make(bpm=60, sub=bad)
    assert onsets(m.render(2000)) == {0: 1.0, 1000: 0.5}


def test_volume_above_one_is_clipped():
    m = make(bpm=60)
    m.volume = 5.0
    out = m.render(10)
    assert out.max() == 1.0
    assert out.min() >= -1.0


def test_negative_volume_is_silent_not_inverted():
    m = make(bpm=60)
    m.volume = -1.0
    assert not m.render(10).any()


def test_set_sound_unknown_name_raises_and_leaves_buffers_intact():
    m = Metronome(samplerate=SR)
    before = m.buffers
    with pytest.raises(KeyError):
        m.set_sound("Nope")
    assert m.buffers is before
    assert m.render(1000).any()


def test_sub_increase_while_next_tick_is_pending_does_not_play_in_the_past():
    m = make(bpm=60, sub=2)
    m.render(400)  # beat 0 played; eighth due at 500, tick 1 pending
    m.subdivision = 4  # sixteenths: tick 1 would be at 250, already past
    out = m.render(900)  # remaining ticks of beat 0 at 500, 750 -> block 100, 350; beat 1 at 600
    assert set(onsets(out)) <= {100, 350, 600, 850}
