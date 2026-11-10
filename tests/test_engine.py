import numpy as np

from metronome.engine import Metronome
from metronome.sound import ACCENT, NORMAL, SUB

SR = 1000  # tiny samplerate keeps the arithmetic readable


def make(bpm=60, bpb=4):
    m = Metronome(bpm=bpm, beats_per_bar=bpb, samplerate=SR)
    # Simple stand-in clicks so the output is easy to inspect.
    m.buffers = {
        ACCENT: np.full(5, 1.0, dtype=np.float32),
        NORMAL: np.full(5, 0.5, dtype=np.float32),
        SUB: np.full(5, 0.25, dtype=np.float32),
    }
    return m


def drain(m):
    out = []
    while not m.beats.empty():
        out.append(m.beats.get_nowait())
    return out


def test_clicks_at_exact_offsets():
    m = make(bpm=120)  # one beat every 500 samples
    signal = np.concatenate([m.render(256) for _ in range(8)])  # 2048 samples
    assert np.flatnonzero(signal).tolist() == [
        s + k for s in (0, 500, 1000, 1500, 2000) for k in range(5)
    ]
    # start_time stays 0, so reported times are block-relative here; just check count.
    assert len(drain(m)) == 5


def test_reported_times_use_stream_clock():
    m = make(bpm=120)
    m.render(1000, start_time=10.0)
    assert [b.time for b in drain(m)] == [10.0, 10.5]


def test_accent_on_first_beat_of_bar():
    m = make(bpm=300, bpb=3)  # beat every 200 samples
    signal = m.render(1000)
    assert [b.beat_in_bar for b in drain(m)] == [0, 1, 2, 0, 1]
    assert signal[[0, 200, 400, 600, 800]].tolist() == [1.0, 0.5, 0.5, 1.0, 0.5]


def test_click_crossing_block_boundary_is_continuous():
    whole = make(bpm=60).render(100)
    m = make(bpm=60)
    split = np.concatenate([m.render(2), m.render(98)])
    np.testing.assert_array_equal(split, whole)


def test_bpm_change_applies_from_next_interval():
    m = make(bpm=60)  # beat at 0, next already scheduled at 1000
    m.render(500, start_time=0.0)
    m.bpm = 120
    m.render(2000, start_time=0.5)
    assert [b.time for b in drain(m)] == [0.0, 1.0, 1.5, 2.0]


def test_beats_per_bar_shrink_wraps_to_downbeat():
    m = make(bpm=300, bpb=4)
    m.render(600)  # beats 0, 1, 2
    m.beats_per_bar = 2
    m.render(400)
    assert [b.beat_in_bar for b in drain(m)] == [0, 1, 2, 0, 1]


def test_bpm_is_clamped():
    m = make()
    m.bpm = 5
    assert m.bpm == 30
