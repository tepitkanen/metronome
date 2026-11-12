"""GUI edge cases for v2: comboboxes, practice fields, dot colours and clicks."""

import tkinter as tk
from tkinter import ttk

import pytest

from metronome import gui
from metronome.engine import Beat
from metronome.sound import ACCENT, MUTE, NORMAL, SOUNDS
from tests.test_gui import _bump, _fake_start, _fake_stop, _key


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


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _boxes(app):
    return [w for w in _descendants(app) if isinstance(w, ttk.Combobox)]


def _fills(app):
    return [app.canvas.itemcget(i, "fill") for i in app.canvas.find_all()]


def _click(app, x):
    app.canvas.event_generate("<Button-1>", x=x, y=10)
    app.root.update()


def test_subdivision_combobox_event_sets_engine_and_swing_state(app):
    sub_box, _ = _boxes(app)
    for name, value in gui.SUBDIVISION_NAMES.items():
        sub_box.set(name)
        sub_box.event_generate("<<ComboboxSelected>>")
        app.root.update()
        assert app.engine.subdivision == value
        assert app.swing_scale.instate(["!disabled"]) == (value == 2)


def test_sound_combobox_event_swaps_buffers(app):
    _, sound_box = _boxes(app)
    for name in SOUNDS:
        sound_box.set(name)
        sound_box.event_generate("<<ComboboxSelected>>")
        app.root.update()
        want = SOUNDS[name](app.engine.samplerate)[ACCENT]
        assert app.engine.buffers[ACCENT].tobytes() == want.tobytes()


def test_selecting_combobox_returns_focus_to_root(app):
    sub_box, _ = _boxes(app)
    sub_box.focus_force()
    app.root.update()
    sub_box.event_generate("<<ComboboxSelected>>")
    app.root.update()
    assert app.root.focus_get() is app.root


def test_shortcuts_ignored_while_combobox_focused(app):
    sub_box, _ = _boxes(app)
    bpm = app.engine.bpm
    for seq in ("<space>", "<t>", "<T>", "<Shift-Up>"):
        _key(app, seq, widget=sub_box)
    assert app.engine.bpm == bpm
    assert not app.engine.running


@pytest.mark.parametrize(
    "name", ["gap_play", "gap_mute", "speed_step", "speed_every", "speed_target"]
)
@pytest.mark.parametrize("text", ["abc", ""])
def test_practice_field_invalid_text_reverts_on_commit(app, name, text):
    var = getattr(app, name)
    good = var.get()
    app.gap_on.set(True)
    app.speed_on.set(True)
    app.apply_trainers()
    tk.Variable.set(var, text)
    app.commit_fields()
    assert var.get() == good
    assert app.engine.gap_bars == (app.gap_play.get(), app.gap_mute.get())


def test_practice_field_out_of_range_clamps_on_commit(app):
    app.gap_play.set(99)
    app.speed_target.set(1000)
    app.speed_every.set(0)
    app.commit_fields()
    assert (app.gap_play.get(), app.speed_target.get(), app.speed_every.get()) == (16, 300, 1)


def test_trainers_toggle_off_and_on_keeps_values(app):
    app.gap_play.set(3)
    app.gap_mute.set(5)
    app.speed_step.set(7)
    app.speed_every.set(9)
    app.speed_target.set(222)
    app.gap_on.set(True)
    app.speed_on.set(True)
    app.apply_trainers()
    first = (app.engine.gap_bars, app.engine.speed)
    assert first == ((3, 5), (7, 9, 222))
    app.gap_on.set(False)
    app.speed_on.set(False)
    app.apply_trainers()
    assert app.engine.gap_bars is None
    assert app.engine.speed is None
    app.gap_on.set(True)
    app.speed_on.set(True)
    app.apply_trainers()
    assert (app.engine.gap_bars, app.engine.speed) == first


def test_editing_field_while_trainer_on_updates_engine_live(app):
    app.gap_on.set(True)
    app.apply_trainers()
    app.gap_play.set(4)
    assert app.engine.gap_bars == (4, 2)


def test_draw_dots_colours_for_muted_gap_silent_and_accent(app):
    app.bpb_var.set(4)
    app.engine.accents = [ACCENT, NORMAL, MUTE, NORMAL]
    app._draw_dots()
    assert _fills(app) == [gui.COLOR_IDLE_ACCENT, gui.COLOR_IDLE, "", gui.COLOR_IDLE]
    items = app.canvas.find_all()
    assert app.canvas.itemcget(items[2], "outline") == gui.COLOR_OUTLINE_MUTE

    app._draw_dots(active=Beat(0, 0.0, ACCENT, True, 120))
    assert _fills(app)[0] == gui.COLOR_ACCENT
    app._draw_dots(active=Beat(1, 0.0, NORMAL, True, 120))
    assert _fills(app)[1] == gui.COLOR_BEAT
    app._draw_dots(active=Beat(2, 0.0, MUTE, True, 120))  # muted beat lit
    assert _fills(app)[2] == gui.COLOR_SILENT
    app._draw_dots(active=Beat(0, 0.0, ACCENT, False, 120))  # gap-silent bar
    assert _fills(app)[0] == gui.COLOR_SILENT
    app._draw_dots(active=Beat(3, 0.0, NORMAL, False, 120))
    assert _fills(app)[3] == gui.COLOR_SILENT


def test_draw_dots_active_index_beyond_bar_is_ignored(app):
    app._draw_dots(active=Beat(9, 0.0, NORMAL, True, 120))
    assert len(app.canvas.find_all()) == app.engine.beats_per_bar


def test_click_on_last_dot_cycles_it(app):
    app.bpb_var.set(4)
    x = 2 + 3 * (gui.DOT_SIZE + gui.DOT_GAP) + gui.DOT_SIZE // 2
    _click(app, x)
    assert app.engine.level_of(3) == MUTE
    assert [app.engine.level_of(i) for i in range(3)] == [ACCENT, NORMAL, NORMAL]


def test_click_beyond_last_dot_or_left_of_first_does_nothing(app):
    app.bpb_var.set(4)
    before = list(app.engine.accents)
    for x in (2 + 4 * (gui.DOT_SIZE + gui.DOT_GAP) + 5, 400, 0, 1):
        _click(app, x)
    assert app.engine.accents == before


def test_bar_heights_ordered_accent_normal_mute_on_common_baseline(app):
    app.bpb_var.set(3)
    app.engine.accents = [ACCENT, NORMAL, MUTE]
    app._draw_dots()
    coords = [app.canvas.coords(i) for i in app.canvas.find_all()]
    heights = [bottom - top for _, top, _, bottom in coords]
    assert heights[0] > heights[1] > heights[2] > 0
    assert len({bottom for *_, bottom in coords}) == 1
    for i, (x0, _, x1, _) in enumerate(coords):
        assert (x0, x1) == (2 + i * (gui.DOT_SIZE + gui.DOT_GAP), x0 + gui.DOT_SIZE)


def _motion(app, x):
    app.canvas.event_generate("<Motion>", x=x, y=10)
    app.root.update()


def test_hover_over_beat_shows_hint_and_hand_cursor_and_leave_clears(app):
    x_beat1 = 2 + (gui.DOT_SIZE + gui.DOT_GAP) + gui.DOT_SIZE // 2
    assert app.accent_hint.cget("text") == ""
    _motion(app, x_beat1)
    assert str(app.canvas.cget("cursor")) == "hand2"
    assert app.accent_hint.cget("text") == gui.ACCENT_HINT

    _motion(app, 2 + gui.DOT_SIZE + gui.DOT_GAP // 2 + 1)  # gap between beats
    assert str(app.canvas.cget("cursor")) == ""
    assert app.accent_hint.cget("text") == ""

    _motion(app, x_beat1)
    app.canvas.event_generate("<Leave>")
    app.root.update()
    assert str(app.canvas.cget("cursor")) == ""
    assert app.accent_hint.cget("text") == ""


# --- collapsible sections / trainer status -------------------------------------


def _section_parts(summary):
    section = summary.master
    button = next(w for w in section.winfo_children() if isinstance(w, ttk.Button))
    body = next(w for w in section.winfo_children() if w.winfo_class() == "TFrame")
    return button, body


@pytest.mark.parametrize(("attr", "title"), [("sound_summary", "Sound"), ("practice_summary", "Practice")])
def test_section_toggle_shows_and_hides_body(app, attr, title):
    button, body = _section_parts(getattr(app, attr))
    assert button.cget("text") == f"▸ {title}"
    assert not body.winfo_ismapped()  # starts collapsed
    button.invoke()
    app.root.update()
    assert body.winfo_ismapped()
    assert button.cget("text") == f"▾ {title}"
    button.invoke()
    app.root.update()
    assert not body.winfo_ismapped()
    assert button.cget("text") == f"▸ {title}"
    assert getattr(app, attr).winfo_ismapped()  # summary stays visible


def test_sound_summary_follows_sound_and_volume(app):
    assert app.sound_summary.cget("text") == f"Beep · {app.volume_var.get()}%"
    app.sound_var.set("Wood")
    app.set_sound()
    app.set_volume(35)
    assert app.sound_summary.cget("text") == "Wood · 35%"


def test_practice_summary_follows_trainers(app):
    assert app.practice_summary.cget("text") == "Off"
    app.gap_on.set(True)
    app.apply_trainers()
    assert app.practice_summary.cget("text") == "Gap 2/2"
    app.gap_mute.set(3)  # spinbox edit applies live
    assert app.practice_summary.cget("text") == "Gap 2/3"
    app.speed_on.set(True)
    app.apply_trainers()
    assert app.practice_summary.cget("text") == "Gap 2/3 · Speed +5/4 bars → 160"
    app.gap_on.set(False)
    app.apply_trainers()
    assert app.practice_summary.cget("text") == "Speed +5/4 bars → 160"


def _poll(app, beat):
    app.engine.stream_time = lambda: 100.0
    app.engine.beats.put(beat)
    app._poll_beats()


def test_status_empty_without_trainer(app):
    app.toggle()
    _poll(app, Beat(0, 1.0, ACCENT, True, 120))
    assert app.status_label.cget("text") == ""


def test_status_shows_gap_playing_and_silent(app):
    app.gap_on.set(True)
    app.apply_trainers()
    app.toggle()
    _poll(app, Beat(0, 1.0, ACCENT, True, 120))
    assert app.status_label.cget("text") == "Playing"
    _poll(app, Beat(0, 2.0, ACCENT, False, 120))
    assert app.status_label.cget("text") == "Silent bar"


def test_status_shows_speed_and_both_then_clears_on_stop(app):
    app.speed_on.set(True)
    app.apply_trainers()
    app.toggle()
    _poll(app, Beat(0, 1.0, ACCENT, True, 125, bumped=True))
    assert app.status_label.cget("text") == "125 → 160 BPM"
    app.gap_on.set(True)
    app.apply_trainers()
    _poll(app, Beat(1, 2.0, NORMAL, False, 125))
    assert app.status_label.cget("text") == "Silent bar · 125 → 160 BPM"
    app.toggle()  # stop
    assert app.status_label.cget("text") == ""


def test_dark_theme_uses_clam_and_palette_background(app):
    assert ttk.Style(app.root).theme_use() == "clam"
    assert app.canvas.cget("background") == gui.COLOR_BG
    assert app.root.cget("background") == gui.COLOR_BG


def test_default_size_uses_default_geometry(app):
    app.rescale(app.winfo_width(), app.winfo_height())
    assert (app.dot_size, app.dot_gap, app.bar_height) == (
        gui.DOT_SIZE, gui.DOT_GAP, gui.BAR_HEIGHT
    )
    assert app.hero_font.cget("size") == gui.HERO_FONT_SIZE


def test_smaller_than_default_never_shrinks(app):
    app.rescale(10, 10)
    assert app.dot_size == gui.DOT_SIZE
    assert app.hero_font.cget("size") == gui.HERO_FONT_SIZE


def test_larger_window_scales_strip_and_hero(app):
    app.bpb_var.set(4)
    w, h = app.winfo_reqwidth(), app.winfo_reqheight()
    app.event_generate("<Configure>", width=2 * w, height=2 * h)
    assert app.dot_size == 2 * gui.DOT_SIZE
    assert app.bar_height == 2 * gui.BAR_HEIGHT
    assert app.hero_font.cget("size") == 2 * gui.HERO_FONT_SIZE
    assert len(app.canvas.find_all()) == 4
    assert int(app.canvas.cget("width")) == 4 + 4 * app.dot_size + 3 * app.dot_gap

    # Hit-testing follows the scaled geometry: the unscaled middle of beat 1 now
    # falls inside beat 0, and the scaled middle of beat 1 cycles beat 1.
    app.engine.accents = [ACCENT, NORMAL, NORMAL, NORMAL]
    assert app._dot_at(2 + gui.DOT_SIZE + gui.DOT_GAP + gui.DOT_SIZE // 2) == 0
    assert app._dot_at(2 + app.dot_size + app.dot_gap + app.dot_size // 2) == 1
    app.cycle_accent(1)
    assert app.engine.level_of(1) == MUTE
    assert len(app.canvas.find_all()) == 4


def test_widening_alone_does_not_scale(app):
    """Height limits the scale too, so the bottom rows never get pushed out of view."""
    app.rescale(3 * app.winfo_reqwidth(), app.winfo_reqheight())
    assert app.dot_size == gui.DOT_SIZE


def test_scaled_bpm_number_is_not_clipped(app):
    """The entry re-lays out its centered text after the font grows (else '120' is cut off)."""
    root = app.root
    try:
        # Like main(): let the App frame fill the window, so resizing reaches rescale().
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.update()
        # Really enlarge the window: a bare rescale() call is undone by the next real
        # <Configure>, because the test window otherwise just fits its content.
        root.geometry(f"{round(1.5 * root.winfo_width())}x{round(1.5 * root.winfo_height())}")
        root.update()
        assert app.hero_font.cget("size") > gui.HERO_FONT_SIZE
        entry = app.hero_entry
        text_w = app.hero_font.measure(entry.get())
        first_x = entry.bbox(0)[0]
        assert first_x + text_w <= entry.winfo_width()
    finally:
        root.columnconfigure(0, weight=0)
        root.rowconfigure(0, weight=0)
        root.geometry("")  # back to content-sized for the other tests
        root.update()


def test_opening_section_grows_a_user_sized_window(app):
    root = app.root
    try:
        root.update()
        # Simulate a hand resize: from now on Tk no longer sizes the window to its content.
        root.geometry(f"{root.winfo_width()}x{root.winfo_height()}")
        root.update()
        button, body = _section_parts(app.practice_summary)
        button.invoke()
        root.update()
        assert root.winfo_height() >= root.winfo_reqheight()
        assert body.winfo_ismapped()
    finally:
        root.geometry("")  # back to content-sized for the other tests
        root.minsize(1, 1)
        root.update()


def test_collapsing_section_returns_focus_from_its_hidden_field(app):
    root = app.root
    button, body = _section_parts(app.practice_summary)
    button.invoke()
    root.update()
    spin = next(w for w in _descendants(body) if isinstance(w, ttk.Spinbox))
    spin.focus_force()
    root.update()
    assert root.focus_get() is spin
    button.invoke()  # takefocus=False: the click leaves focus in the field
    root.update()
    assert root.focus_get() is root  # Space/T shortcuts work again


# --- QA round: tempo hero, spaces in fields, strip, resizing --------------------


def _type(entry, text):
    entry.focus_force()
    entry.master.update()
    entry.delete(0, "end")
    entry.insert(0, text)


@pytest.mark.parametrize("key", ["<Return>", "<Escape>"])
@pytest.mark.parametrize(("text", "want"), [("999", 300), ("5", 30), ("abc", 120), ("", 120)])
def test_bpm_entry_return_escape_commit_and_free_focus(app, key, text, want):
    entry = app.hero_entry
    _type(entry, text)
    _key(app, key, widget=entry)
    assert app.root.focus_get() is app.root
    assert app.engine.bpm == want
    assert entry.get() == str(want)
    assert app.tempo_label.cget("text") == gui.tempo_name(want)


def test_bpm_entry_focus_out_commits(app):
    entry = app.hero_entry
    _type(entry, "1000")
    app.root.focus_force()
    app.root.update()
    assert entry.get() == "300"
    assert app.engine.bpm == 300


def test_bpm_entry_live_valid_text_updates_engine_and_label(app):
    _type(app.hero_entry, "60")
    assert app.engine.bpm == 60
    assert app.tempo_label.cget("text") == "Larghetto"


def test_hero_plus_minus_buttons_nudge_and_clamp(app):
    hero = app.tempo_label.master
    minus, plus = [w for w in hero.winfo_children() if isinstance(w, ttk.Button)]
    app.bpm_var.set(120)
    plus.invoke()
    assert app.engine.bpm == 121
    minus.invoke()
    minus.invoke()
    assert app.engine.bpm == 119
    app.bpm_var.set(300)
    plus.invoke()
    assert app.engine.bpm == 300
    app.bpm_var.set(30)
    minus.invoke()
    assert app.engine.bpm == 30


def test_wheel_over_entry_nudges_and_clamps_half_typed_text(app):
    _type(app.hero_entry, "999")
    app.hero_entry.event_generate("<MouseWheel>", delta=-120)
    assert app.engine.bpm == 299
    assert app.hero_entry.get() == "299"
    app.bpm_var.set(300)
    app.hero_entry.event_generate("<MouseWheel>", delta=120)
    assert app.engine.bpm == 300


def test_wheel_on_every_hero_widget_nudges(app):
    hero = app.tempo_label.master
    app.bpm_var.set(100)
    for widget in (hero, *hero.winfo_children()):
        widget.event_generate("<MouseWheel>", delta=120)
    assert app.engine.bpm == 100 + len(hero.winfo_children()) + 1


def test_tap_button_sets_tempo(app):
    ticks = iter([0.0, 0.4])
    app.tapper.clock = lambda: next(ticks)
    tap = next(w for w in app.winfo_children() if isinstance(w, ttk.Button) and w.cget("text") == "Tap")
    tap.invoke()
    tap.invoke()
    assert app.engine.bpm == 150


def test_tempo_label_follows_speed_trainer_bump(app):
    app.bpm_var.set(100)
    _poll(app, Beat(0, 0.0, NORMAL, True, 125, True))
    assert app.bpm_var.get() == 125
    assert app.tempo_label.cget("text") == "Allegro"


def _open(app, summary):
    button, body = _section_parts(summary)
    button.invoke()
    app.root.update()
    return body


def test_space_in_every_practice_spinbox_toggles_and_frees_focus(app):
    body = _open(app, app.practice_summary)
    spins = [w for w in _descendants(body) if isinstance(w, ttk.Spinbox)]
    assert len(spins) == 5
    for spin in spins:
        before = spin.get()
        _key(app, "<space>", widget=spin)
        assert spin.get() == before  # no space inserted
        assert app.root.focus_get() is app.root
        assert app.engine.running
        _key(app, "<space>")
        assert not app.engine.running


def test_space_in_practice_spinbox_commits_out_of_range(app):
    body = _open(app, app.practice_summary)
    spin = next(w for w in _descendants(body) if isinstance(w, ttk.Spinbox))
    _type(spin, "99")
    _key(app, "<space>", widget=spin)
    assert app.gap_play.get() == 16


def test_space_in_beats_per_bar_spinbox_commits_and_toggles(app):
    spin = _spinboxes_top(app)[0]
    _type(spin, "50")
    _key(app, "<space>", widget=spin)
    assert app.engine.beats_per_bar == 12
    assert app.engine.running


def _spinboxes_top(app):
    return [w for w in app.winfo_children() if isinstance(w, ttk.Spinbox)]


def test_space_in_sound_combobox_does_nothing(app):
    body = _open(app, app.sound_summary)
    box = next(w for w in _descendants(body) if isinstance(w, ttk.Combobox))
    _key(app, "<space>", widget=box)
    assert not app.engine.running


@pytest.mark.parametrize("n", range(1, 13))
def test_strip_has_one_bar_per_beat_and_geometry_fits(app, n):
    app.bpb_var.set(n)
    items = app.canvas.find_all()
    assert len(items) == n
    assert int(app.canvas.cget("width")) == 4 + n * gui.DOT_SIZE + (n - 1) * gui.DOT_GAP
    right = max(app.canvas.coords(i)[2] for i in items)
    assert right + 2 <= int(app.canvas.cget("width"))
    assert app._dot_at(2 + (n - 1) * (gui.DOT_SIZE + gui.DOT_GAP) + 1) == n - 1
    assert app._dot_at(2 + n * (gui.DOT_SIZE + gui.DOT_GAP) + 1) is None


def test_click_cycles_full_loop_through_events(app):
    x = 2 + gui.DOT_SIZE // 2
    levels = []
    for _ in range(3):
        _click(app, x)
        levels.append(app.engine.level_of(0))
    assert levels == [NORMAL, MUTE, ACCENT]


def test_rescale_never_below_one_for_degenerate_sizes(app):
    for size in ((0, 0), (1, 1), (0, 500), (500, 0)):
        app.rescale(*size)
        assert app._scale == 1.0
        assert app.dot_size == gui.DOT_SIZE


def test_rescale_uses_smaller_axis_ratio(app):
    w, h = app.winfo_reqwidth(), app.winfo_reqheight()
    app.rescale(3 * w, 2 * h)
    assert app.dot_size == 2 * gui.DOT_SIZE
    app.rescale(2 * w, 3 * h)
    assert app.dot_size == 2 * gui.DOT_SIZE


def test_adding_beats_grows_a_user_sized_window(app):
    root = app.root
    try:
        app.bpb_var.set(2)
        root.update()
        root.geometry(f"{root.winfo_width()}x{root.winfo_height()}")
        root.update()
        app.bpb_var.set(12)
        root.update()
        assert root.winfo_width() >= root.winfo_reqwidth()
        assert root.winfo_width() >= 4 + 12 * gui.DOT_SIZE + 11 * gui.DOT_GAP
    finally:
        root.geometry("")
        root.minsize(1, 1)
        root.update()


def test_stop_restores_base_after_bump_and_clears_status(app):
    app.bpm_var.set(100)
    app.speed_on.set(True)
    app.apply_trainers()
    app.toggle()
    _bump(app, 120)
    _poll(app, Beat(0, 0.0, NORMAL, True, 120, True))
    assert "→" in app.status_label.cget("text")
    app.toggle()
    assert app.bpm_var.get() == 100
    assert app.engine.bpm == 100
    assert app.status_label.cget("text") == ""


@pytest.mark.parametrize("text", ["inf", "-inf", "1e999"])
def test_commit_fields_survives_infinite_text(app, text):
    """IntVar.get() raises OverflowError (not TclError) for these; typing them must not crash."""
    tk.Variable.set(app.bpm_var, text)
    app.commit_fields()
    assert app.bpm_var.get() == 120


def test_commit_normalises_decimal_text(app):
    _type(app.hero_entry, "120.7")
    _key(app, "<Return>", widget=app.hero_entry)
    assert app.hero_entry.get() == str(app.engine.bpm)
