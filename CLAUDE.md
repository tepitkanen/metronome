# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Desktop metronome: tkinter GUI, click synthesized with numpy, played via `sounddevice` (PortAudio). Python 3.14, Windows.

## Commands
Everything runs from the project venv (`.venv`, git-ignored):
```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m metronome                      # run the app
.venv\Scripts\python -m pytest                         # all tests
.venv\Scripts\python -m pytest tests/test_engine.py::test_clicks_at_exact_offsets   # one test
.venv\Scripts\python -m ruff check .                   # lint (a global ruff config enables extra rules, e.g. BLE001)
```

## Architecture
Timing is sample-accurate and must stay that way. Never schedule clicks with `time.sleep`, threads, or Tk `after()`.

- `engine.Metronome` owns a continuous `sd.OutputStream`. Its callback calls `render(frames, start_time)`, which mixes click buffers into the block at exact sample offsets.
- **Tick scheduling:** each beat is split into `subdivision` ticks (1–4). `_beat_start` is the current beat's float sample position relative to the block start. Each tick sits at `_beat_start + _beat_interval * frac`, where `frac = tick/sub`, or `swing` for the offbeat eighth. `_tails` holds the remainder of clicks that cross a block boundary. `_start_beat()` runs on each beat's first tick. It latches `_beat_interval`, so a BPM change applies from the next beat. It also advances `_bar` and applies both trainers. Output is scaled by `volume`, then clipped to [-1, 1].
- `render()` is pure apart from engine state and needs no audio device. Tests drive it directly with a tiny samplerate and stand-in `buffers` arrays (`tests/test_engine*.py`).
- **Settings** (`bpm`, `beats_per_bar`, `subdivision`, `swing`, `accents`, `volume`, `buffers`, `gap_bars`, `speed`) are plain attributes that the callback reads once per block. Lists, tuples and dicts must be *replaced*, never mutated in place, because the audio thread may be reading them. If beats-per-bar shrinks mid-bar, the count wraps to the downbeat.
- **Levels:** `sound.py` defines `MUTE`/`NORMAL`/`ACCENT`, which are per-beat levels in `engine.accents`, and `SUB`. All four are keys into a `SOUNDS[name](samplerate)` buffer bank. Beats beyond `len(accents)` use `default_level()`, which accents beat 0. A muted beat also silences its subdivisions.
- **Audio → GUI:** on each main beat (not on sub ticks), the callback puts a `Beat(beat_in_bar, time, level, audible, bpm, bumped)` on `engine.beats` (a `SimpleQueue`). `gui.App._poll_beats` drains it every 10 ms and lights that beat's bar (one canvas item per beat; bar height also shows its accent level) once `engine.stream_time()` reaches `Beat.time`, so the visual matches what you hear despite output latency. The BPM field follows the engine only when `bumped` is set by the speed trainer. Syncing on every `bpm` change instead would let stale queued beats undo the user's own tempo edits. The audio thread must never touch Tk.
- **Stop undoes the speed-trainer ramp.** `App._base_bpm` is the last tempo the user set; mirroring a bump sets `_showing_bump`, so it doesn't count. On Stop, the BPM returns to `_base_bpm` if the engine's tempo differs from it.
- `tempo.py` holds pure helpers: `clamp_bpm` (30–300, the single source of BPM limits), `TapTempo` and `tempo_name` (the Italian marking shown above the BPM).
- **Keyboard shortcuts** are bound on the root window and skipped while an Entry/Spinbox/Combobox has focus. The exception is Space in a number field (the BPM entry or a spinbox): a number never contains a space, so it commits the field, returns focus to the root and starts/stops. Buttons, sliders and checkbuttons use `takefocus=False` so Space and the arrow keys don't trigger them twice. Comboboxes return focus to the root after a selection.
- **Spinboxes** are wrapped in `gui.IntField`. Text is applied live only when it's a valid in-range value. `App.commit_fields()` runs on FocusOut, Return and Escape: it clamps each typed value, or reverts invalid text to the last valid value, and writes it back.

## GUI tests
`tests/test_gui.py` stubs `engine.start`/`stop`, so no audio device is needed. It shares one session-scoped `tk.Tk()` (`tests/conftest.py`, used by every `test_gui*.py`), because creating it repeatedly in one process fails intermittently on Windows ("Can't find a usable init.tcl"). It keeps the root mapped off-screen rather than withdrawn, because a withdrawn window can't take focus and the key-event tests would then pass without testing anything.
