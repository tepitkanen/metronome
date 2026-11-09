from tkinter import ttk

import pytest

from metronome import gui
from metronome.engine import Beat
from metronome.sound import ACCENT, MUTE, NORMAL


def _fake_start(self):
    self._stream = object()


def _fake_stop(self):
    self._stream = None


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


def test_bpb_out_of_range_clamped_on_commit(app):
    app.bpb_var.set(99)
    assert app.engine.beats_per_bar == 4  # ignored while typing
    app.commit_fields()
    assert app.engine.beats_per_bar == 12
    app.bpb_var.set(-3)
    app.commit_fields()
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
    beat = Beat(2, 5.0, NORMAL, True, 120)
    app.engine.beats.put(beat)
    app._poll_beats()
    assert app._pending == [beat]
    app.engine.stream_time = lambda: 5.0
    app._poll_beats()
    assert app._pending == []


# --- v2 features -------------------------------------------------------------


def _dot_fills(app):
    return [app.canvas.itemcget(i, "fill") for i in app.canvas.find_all()]


def test_dot_click_cycles_accent_levels(app):
    x_beat1 = 2 + (gui.DOT_SIZE + gui.DOT_GAP) + gui.DOT_SIZE // 2
    seen = []
    for _ in range(3):
        app.canvas.event_generate("<Button-1>", x=x_beat1, y=10)
        app.root.update()
        seen.append(app.engine.level_of(1))
    assert seen == [MUTE, ACCENT, NORMAL]
    assert app.engine.level_of(0) == ACCENT  # other beats untouched


def test_click_in_gap_between_dots_does_nothing(app):
    x_gap = 2 + gui.DOT_SIZE + gui.DOT_GAP // 2 + 1
    app.canvas.event_generate("<Button-1>", x=x_gap, y=10)
    app.root.update()
    assert app.engine.accents == []


def test_muted_dot_drawn_hollow(app):
    app.cycle_accent(1)  # NORMAL -> MUTE
    assert _dot_fills(app)[1] == ""


def test_accents_survive_beats_per_bar_shrink_and_grow(app):
    app.cycle_accent(3)  # beat 4 -> MUTE
    app.bpb_var.set(2)
    app.bpb_var.set(4)
    assert app.engine.level_of(3) == MUTE


def test_swing_enabled_only_for_eighths(app):
    for name, enabled in (("Eighths", True), ("Triplets", False), ("Quarter notes", False)):
        app.sub_var.set(name)
        app.set_subdivision()
        assert app.swing_scale.instate(["disabled"]) is not enabled
    app.sub_var.set("Sixteenths")
    app.set_subdivision()
    assert app.engine.subdivision == 4


def test_swing_and_volume_update_engine(app):
    app.set_swing(66)
    assert app.engine.swing == 0.66
    assert app.swing_label.cget("text") == "66%"
    app.set_volume(40)
    assert app.engine.volume == 0.4


def test_sound_selection_changes_buffers(app):
    before = app.engine.buffers
    app.sound_var.set("Wood")
    app.set_sound()
    assert app.engine.buffers is not before


def test_trainers_apply_only_when_checked(app):
    app.gap_play.set(3)
    assert app.engine.gap_bars is None
    app.gap_on.set(True)
    app.apply_trainers()
    assert app.engine.gap_bars == (3, 2)
    app.speed_on.set(True)
    app.apply_trainers()
    assert app.engine.speed == (5, 4, 160)
    app.speed_step.set(10)  # live update while enabled
    assert app.engine.speed == (10, 4, 160)
    app.gap_on.set(False)
    app.apply_trainers()
    assert app.engine.gap_bars is None


def test_trainer_spinbox_clamps_on_commit(app):
    app.speed_on.set(True)
    app.speed_target.set(999)
    app.commit_fields()
    assert app.speed_target.get() == 300
    assert app.engine.speed[2] == 300


def test_speed_trainer_bump_updates_bpm_field(app):
    app.toggle()
    app.engine.stream_time = lambda: 10.0
    app.engine.beats.put(Beat(0, 1.0, ACCENT, True, 125, bumped=True))
    app._poll_beats()
    assert app.bpm_var.get() == 125


def test_stale_beat_without_bump_does_not_override_user_bpm(app):
    app.toggle()
    app.bpm_var.set(150)  # user change; queued beat still carries the old tempo
    app.engine.stream_time = lambda: 10.0
    app.engine.beats.put(Beat(0, 1.0, ACCENT, True, 120))
    app._poll_beats()
    assert app.bpm_var.get() == 150


def _bump(app, bpm):
    app.engine.bpm = bpm  # what the speed trainer does inside render()
    app.engine.stream_time = lambda: 10.0
    app.engine.beats.put(Beat(0, 1.0, ACCENT, True, bpm, bumped=True))
    app._poll_beats()


def test_stop_restores_tempo_before_speed_trainer_ramp(app):
    app.bpm_var.set(100)
    app.toggle()
    _bump(app, 110)
    _bump(app, 120)
    assert app.bpm_var.get() == 120
    app.toggle()  # stop
    assert app.engine.bpm == 100
    assert app.bpm_var.get() == 100


def test_stop_restores_even_if_bump_not_yet_displayed(app):
    app.bpm_var.set(100)
    app.toggle()
    app.engine.bpm = 130  # trainer bumped in the audio thread; beat still pending
    app.toggle()
    assert app.engine.bpm == 100
    assert app.bpm_var.get() == 100


def test_user_tempo_change_during_ramp_becomes_new_base(app):
    app.bpm_var.set(100)
    app.toggle()
    _bump(app, 110)
    app.nudge(5)  # user takes over at 115
    _bump(app, 125)
    app.toggle()
    assert app.bpm_var.get() == 115


def test_stop_without_trainer_keeps_tempo(app):
    app.bpm_var.set(140)
    app.toggle()
    app.toggle()
    assert app.bpm_var.get() == 140
