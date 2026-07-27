"""
Shade Engine - single entry point.

The SAME executable serves two roles:
  * default            -> launches the graphical app (GUI)
  * with --engine flag -> runs the packet-injection backend

The GUI relaunches this same exe with --engine when you press START, so the
whole product ships as ONE self-contained executable (no separate engine.exe).
"""

import multiprocessing
import sys


def main():
    if "--engine" in sys.argv:
        from engine_core import run_engine
        run_engine()
    else:
        from gui import run_gui
        run_gui()


if __name__ == "__main__":
    # Safe no-op in a normal build; protects against odd re-spawns.
    multiprocessing.freeze_support()
    main()
