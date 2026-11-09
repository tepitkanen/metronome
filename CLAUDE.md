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

- `engine.Metronome` owns a continuous `sd.OutputStream`. Its callback calls `render(frames, start_time)`, which mixes click buffers into the block at exact sample offsets. `_next_beat` is the float sample position of the next beat relative to the block start, and `_tails` holds the remainder of clicks that cross a block boundary.
- `render()` is pure apart from engine state and needs no audio device. Tests drive it directly with a tiny samplerate and stand-in click arrays (`tests/test_engine.py`).
- BPM and beats-per-bar are plain attributes that the callback reads once per block. A BPM change applies from the next scheduled beat. If beats-per-bar shrinks mid-bar, the count wraps to the downbeat.
- **Audio → GUI:** the callback puts `(beat_in_bar, dac_time)` on `engine.beats` (a `SimpleQueue`). `gui.App._poll_beats` drains it every 10 ms and lights a dot once `engine.stream_time()` reaches `dac_time`, so the visual matches what you hear despite output latency. The audio thread must never touch Tk.
- `tempo.py` holds pure helpers: `clamp_bpm` (30–300, the single source of BPM limits) and `TapTempo`.
- **Keyboard shortcuts** are bound on the root window and skipped while an Entry/Spinbox has focus. Buttons and the slider use `takefocus=False` so Space and the arrow keys don't trigger them twice.
- **Spinbox text** is applied live only when it's a valid in-range value. `App.commit_fields()` runs on FocusOut, Return and Escape: it clamps the typed value, or reverts invalid text, and writes it back.

## GUI tests
`tests/test_gui.py` stubs `engine.start`/`stop`, so no audio device is needed. It shares one module-scoped `tk.Tk()`, because creating it repeatedly in one process fails intermittently on Windows ("Can't find a usable init.tcl"). It keeps the root mapped off-screen rather than withdrawn, because a withdrawn window can't take focus and the key-event tests would then pass without testing anything.
