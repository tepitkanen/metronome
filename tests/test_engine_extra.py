import math

import numpy as np

from metronome.engine import Metronome
from metronome.sound import ACCENT, NORMAL, SUB, make_click


def make(bpm=60, bpb=4, sr=1000, click_len=5):
    m = Metronome(bpm=bpm, beats_per_bar=bpb, samplerate=sr)
    m.buffers = {
        ACCENT: np.full(click_len, 1.0, dtype=np.float32),
        NORMAL: np.full(click_len, 0.5, dtype=np.float32),
        SUB: np.full(click_len, 0.25, dtype=np.float32),
    }
    return m


def drain(m):
    out = []
    while not m.beats.empty():
        out.append(m.beats.get_nowait())
    return out


def test_long_run_no_cumulative_drift():
    sr, bpm, block = 44100, 97, 512
    m = Metronome(bpm=bpm, samplerate=sr)
    interval = sr * 60.0 / bpm
    blocks = 6000
    beats = []
    for i in range(blocks):
        m.render(block, start_time=i * block / sr)
        beats.extend(drain(m))
    expected = math.ceil(blocks * block / interval)
    assert len(beats) == expected
    for k, t in enumerate(b.time for b in beats):
        # one sample of truncation is fine, a growing error is not
        assert abs(t * sr - k * interval) < 1.0 + 1e-6, k


def test_long_run_irregular_block_sizes_match_grid():
    sr, bpm = 44100, 133
    m = Metronome(bpm=bpm, samplerate=sr)
    interval = sr * 60.0 / bpm
    rng = np.random.default_rng(1)
    pos = 0
    times = []
    for _ in range(3000):
        n = int(rng.integers(1, 2000))
        m.render(n, start_time=pos / sr)
        times += [b.time for b in drain(m)]
        pos += n
    assert len(times) == math.ceil(pos / interval)
    for k, t in enumerate(times):
        assert abs(t * sr - k * interval) < 1.0 + 1e-6


def test_zero_frames_is_noop():
    m = make()
    out = m.render(0)
    assert out.shape == (0,)
    assert drain(m) == []
    assert m.render(10)[:5].tolist() == [1.0] * 5


def test_one_frame_blocks_equal_one_big_block():
    whole = make(bpm=300).render(1000)
    m = make(bpm=300)
    split = np.concatenate([m.render(1) for _ in range(1000)])
    np.testing.assert_array_equal(split, whole)


def test_click_longer_than_interval_overlaps_additively():
    m = make(bpm=300, click_len=300)  # interval 200, click 300
    m.volume = 0.5  # keep sums below the [-1, 1] output clip
    out = m.render(1000)
    assert out[0] == 0.5  # accent alone
    assert out[199] == 0.5
    assert math.isclose(out[200], 0.75)  # accent tail + click 1
    assert math.isclose(out[299], 0.75)
    assert math.isclose(out[300], 0.25)  # accent over, click 1 only
    assert math.isclose(out[400], 0.5)  # clicks 1 and 2


def test_overlapping_clicks_are_clipped_to_unit_range():
    m = make(bpm=300, click_len=300)
    out = m.render(1000)
    assert out[200] == 1.0  # 1.5 before clipping
    assert np.abs(out).max() <= 1.0


def test_overlapping_clicks_split_across_blocks_match_whole():
    whole = make(bpm=300, click_len=700).render(1500)
    m = make(bpm=300, click_len=700)
    split = np.concatenate([m.render(n) for n in (1, 7, 100, 3, 389, 500, 500)])
    np.testing.assert_allclose(split, whole)


def test_tail_longer_than_block_survives_tiny_blocks():
    m = make(bpm=30, click_len=50)
    out = np.concatenate([m.render(3) for _ in range(20)])
    assert np.count_nonzero(out) == 50


def test_beats_per_bar_grow_continues_count():
    m = make(bpm=300, bpb=2)
    m.render(400)  # 0, 1
    m.beats_per_bar = 4
    m.render(600)
    assert [b.beat_in_bar for b in drain(m)] == [0, 1, 2, 3, 0]


def test_beats_per_bar_zero_treated_as_one():
    m = make(bpm=300, bpb=0)
    m.render(600)
    assert [b.beat_in_bar for b in drain(m)] == [0, 0, 0]


def test_reset_restarts_bar_and_clock():
    m = make(bpm=300)
    m.render(450)
    drain(m)
    m.reset()
    out = m.render(3)
    assert [(b.beat_in_bar, b.time) for b in drain(m)] == [(0, 0.0)]
    assert out.tolist() == [1.0, 1.0, 1.0]


def test_reset_drops_pending_tail():
    m = make(bpm=30)
    m.render(2)  # click at 0, 3 samples pending
    m.reset()
    # fresh beat at 0 again, so use a tail-free check: tail must not add on top
    out = m.render(10)
    assert out[:5].tolist() == [1.0] * 5
    m2 = make(bpm=30)
    m2.render(2)
    m2._beat_start = 100.0  # no new beat in the next block
    m2.reset()
    m2._beat_start = 100.0
    assert not m2.render(10).any()


def test_make_click_properties():
    for sr in (8000, 44100, 48000):
        c = make_click(1000, sr, ms=30.0, volume=0.6)
        assert c.dtype == np.float32
        assert c.ndim == 1
        assert len(c) == int(sr * 30.0 / 1000)
        assert np.max(np.abs(c)) <= 0.6 + 1e-6
        assert abs(c[0]) < 1e-3
        assert np.isfinite(c).all()


def test_make_click_tiny_durations_do_not_crash():
    assert len(make_click(1000, 44100, ms=0.0)) == 0
    c = make_click(1000, 1000, ms=1.0)
    assert len(c) == 1
    assert c.dtype == np.float32
