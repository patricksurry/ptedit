"""Line-profile the rendering hot path against a perftest scenario.

Usage:
    uv run python tools/profile_perf.py <scenario>

where <scenario> is one of: insert, up_from_end, pgup_from_end, pgdn_from_top.
Defaults to up_from_end.
"""
import sys

from line_profiler import LineProfiler

from ptedit.controller import Controller
from ptedit.screen import Screen
from ptedit.display import Display
from ptedit.layout import Layout


def main(scenario: str = "up_from_end") -> None:
    ctrl = Controller("tests/alice1flow.asc", Screen(24, 80))

    lp = LineProfiler()
    # Display side: paint orchestration and the screen anchor.
    lp.add_function(Display.find_top)
    lp.add_function(Display.paint)
    lp.add_function(Display._render_rows)
    # Layout side: Phase 1 helpers + BoL nav.
    lp.add_function(Layout.ensure_bracketed)
    lp.add_function(Layout.line_index)
    lp.add_function(Layout.line_index_of_loc)
    lp.add_function(Layout.clamp_to_bol)
    lp.add_function(Layout.bol_to_next_bol)
    lp.add_function(Layout.bol_to_prev_bol)
    lp.add_function(Layout.reanchor)
    lp.add_function(Layout._extend_to)
    lp.add_function(Layout.note_change)
    lp.add_function(Layout.format_line)

    wrapped = lp(ctrl.perftest)
    print(wrapped(scenario))
    lp.print_stats(stripzeros=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "up_from_end")
