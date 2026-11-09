import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    # Creating/destroying Tk() more than once per process is unreliable on Windows
    # ("invalid command name tcl_findLibrary"), so all GUI test modules share one root.
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
