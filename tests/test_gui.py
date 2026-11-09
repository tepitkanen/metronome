import tkinter as tk
from tkinter import ttk

import pytest

from metronome import gui


def _fake_start(self):
    self._stream = object()


def _fake_stop(self):
    self._stream = None


@pytest.fixture(scope="module")
def tk_root():
    # Repeatedly creating/destroying Tk() in one process is unreliable on
    # Windows, so share one hidden root across the module.
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    # A withdrawn window can't take keyboard focus, so key events would all go
    # to the root. Keep it mapped but off-screen instead.
    root.geometry("+-3000+-3000")
    root.update()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, monkeypatch):
    monkeypatch.setattr(gui.Metronome, "start", _fake_start)
    monkeypatch.setattr(gui.Metronome, "stop", _fake_stop)
    a = gui.App(tk_root)
    tk_root.update()
    yield a
    a.destroy()
    for seq in ("<space>", "<Up>", "<Down>", "<Shift-Up>", "<Shift-Down>", "<t>", "<T>"):
        tk_root.unbind(seq)


def _spinboxes(app):
    return [w for w in app.winfo_children() if isinstance(w, ttk.Spinbox)]


def _key(app, seq, widget=None):
    w = widget or app.root
    w.focus_force()
    app.root.update()
    assert app.root.focus_get() is w, "widget did not receive focus"
    w.event_generate(seq)
    app.root.update()


def test_nudge_clamps(app):
    app.bpm_var.set(295)
    app.nudge(10)
    assert app.bpm_var.get() == 300
    assert app.engine.bpm == 300
    app.bpm_var.set(35)
    app.nudge(-10)
    assert app.bpm_var.get() == 30
    assert app.engine.bpm == 30


def test_tap_updates_bpm_var(app):
    ticks = iter([0.0, 0.5])
    app.tapper.clock = lambda: next(ticks)
    app.bpm_var.set(60)
    app.tap()
    assert app.bpm_var.get() == 60  # first tap gives no tempo
    app.tap()
    assert app.bpm_var.get() == 120
    assert app.engine.bpm == 120


def test_bpm_trace_updates_engine(app):
    app.bpm_var.set(77)
    assert app.engine.bpm == 77


def test_bpb_trace_updates_engine_and_dots(app):
    app.bpb_var.set(6)
    assert app.engine.beats_per_bar == 6
    assert len(app.canvas.find_all()) == 6


def test_bpb_out_of_range_clamped_in_engine(app):
    app.bpb_var.set(99)
    assert app.engine.beats_per_bar == 12
    app.bpb_var.set(-3)
    assert app.engine.beats_per_bar == 1


@pytest.mark.parametrize("text", ["", "abc", "1x", "-"])
def test_invalid_spinbox_text_does_not_crash(app, text):
    app.root.tk.globalsetvar(str(app.bpm_var), text)
    app.root.tk.globalsetvar(str(app.bpb_var), text)
    app.root.update()
    assert app.engine.bpm == 120
    assert app.engine.beats_per_bar == 4


def test_out_of_range_typed_bpm_is_ignored_until_committed(app):
    app.root.tk.globalsetvar(str(app.bpm_var), "5")  # on the way to "50"
    assert app.engine.bpm == 120
    app.root.tk.globalsetvar(str(app.bpm_var), "5000")
    assert app.engine.bpm == 120
    app.commit_fields()
    assert app.engine.bpm == 300
    assert app.bpm_var.get() == 300


def test_commit_fields_reverts_invalid_text(app):
    app.root.tk.globalsetvar(str(app.bpm_var), "abc")
    app.root.tk.globalsetvar(str(app.bpb_var), "")
    app.commit_fields()
    assert app.bpm_var.get() == 120
    assert app.bpb_var.get() == 4


def test_commit_fields_shows_clamped_beats_per_bar(app):
    app.bpb_var.set(99)
    app.commit_fields()
    assert app.bpb_var.get() == 12


def test_shortcuts_work_on_root(app):
    _key(app, "<Up>")
    assert app.engine.bpm == 121
    _key(app, "<Shift-Down>")
    assert app.engine.bpm == 111
    _key(app, "<space>")
    assert app.engine.running


def test_nudge_and_toggle_ignored_when_spinbox_focused(app):
    spin = _spinboxes(app)[0]
    calls = []
    app.nudge = calls.append
    for seq in ("<Up>", "<Down>", "<Shift-Up>", "<space>"):
        _key(app, seq, widget=spin)
    assert calls == []
    assert not app.engine.running


def test_tap_key_ignored_when_spinbox_focused(app):
    spin = _spinboxes(app)[0]
    calls = []
    app.tap = lambda: calls.append(1)
    _key(app, "<t>", widget=spin)
    assert calls == []


def test_toggle_updates_button_text(app):
    assert app.start_btn.cget("text") == "Start"
    app.toggle()
    assert app.start_btn.cget("text") == "Stop"
    assert app.engine.running
    app.toggle()
    assert app.start_btn.cget("text") == "Start"
    assert not app.engine.running


def test_audio_error_shows_messagebox_and_keeps_state(app, monkeypatch):
    shown = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: shown.append(a))

    def boom(self):
        raise gui.sd.PortAudioError("no device")

    monkeypatch.setattr(gui.Metronome, "start", boom)
    app.toggle()
    assert len(shown) == 1
    assert "no device" in shown[0][1]
    assert app.start_btn.cget("text") == "Start"
    assert not app.engine.running


def test_toggle_clears_stale_beats(app):
    app.engine.beats.put((0, 0.0))
    app._pending.append((1, 0.0))
    app.toggle()
    assert app.engine.beats.empty()
    assert app._pending == []


def test_poll_lights_dot_only_when_due(app):
    app.toggle()
    app.engine.stream_time = lambda: 1.0
    app.engine.beats.put((2, 5.0))
    app._poll_beats()
    assert app._pending == [(2, 5.0)]
    app.engine.stream_time = lambda: 5.0
    app._poll_beats()
    assert app._pending == []
