"""Instrument the insert perftest to count reanchors and recenters.

Wraps the relevant methods with counters and reports per-frame stats so
we can see exactly why the ladder rebuilds.

Usage:
    uv run python tools/trace_insert.py
"""
from time import time

from ptedit.controller import Controller
from ptedit.screen import Screen


def main() -> None:
    ctrl = Controller("tests/alice1flow.asc", Screen(24, 80))
    layout = ctrl.dpy.layout

    stats = {
        "frames": 0,
        "find_top_calls": 0,
        "find_top_sticky": 0,
        "find_top_recenter": 0,
        "top_loc_missing_from_ladder": 0,
        "ensure_bracketed_reanchor": 0,
        "ensure_bracketed_extend": 0,
        "ensure_bracketed_bracketed": 0,
        "bol_to_prev_bol_fallback": 0,   # the case that triggers reanchor inside bol_to_prev_bol
        "reanchor_calls": 0,
        "ladder_lens": [],               # ladder length at start of each find_top
    }

    # Wrap reanchor
    orig_reanchor = layout.reanchor
    def reanchor(cursor):
        stats["reanchor_calls"] += 1
        return orig_reanchor(cursor)
    layout.reanchor = reanchor

    # Wrap ensure_bracketed to count cases
    orig_locate = layout._locate_cursor if hasattr(layout, "_locate_cursor") else None
    orig_ensure = layout.ensure_bracketed
    def ensure_bracketed(cursor):
        lad = layout.bol_ladder
        if not lad or cursor.is_strictly_before(lad[0]):
            stats["ensure_bracketed_reanchor"] += 1
        elif cursor.is_strictly_before(lad[-1]):
            stats["ensure_bracketed_bracketed"] += 1
        else:
            gap = cursor.distance_after(lad[-1])
            if gap is None or gap > layout.rows * layout.cols:
                stats["ensure_bracketed_reanchor"] += 1
            else:
                stats["ensure_bracketed_extend"] += 1
        return orig_ensure(cursor)
    layout.ensure_bracketed = ensure_bracketed

    # Wrap bol_to_prev_bol to count the fallback case
    orig_bol_to_prev_bol = layout.bol_to_prev_bol
    def bol_to_prev_bol():
        if not ctrl.doc.at_start():
            bol = ctrl.doc.get_point()
            i = layout.line_index(bol)
            if i == 0:
                stats["bol_to_prev_bol_fallback"] += 1
        return orig_bol_to_prev_bol()
    layout.bol_to_prev_bol = bol_to_prev_bol

    # Wrap find_top
    orig_find_top = ctrl.dpy.find_top
    def find_top():
        stats["find_top_calls"] += 1
        stats["ladder_lens"].append(len(layout.bol_ladder))
        old_top_loc = ctrl.dpy.top_loc
        # Was top_loc findable in the ladder before find_top runs?
        if old_top_loc is not None:
            found = any(e == old_top_loc for e in layout.bol_ladder)
            if not found:
                stats["top_loc_missing_from_ladder"] += 1
        # Detect sticky vs recenter via the post-condition heuristic:
        # if cur_idx - top_idx is in [0, rows) we'd be sticky.
        result = orig_find_top()
        # (Easier: detect via the path taken — but the function is opaque
        # without further patching. Use a proxy: recenter walks back
        # preferred_row lines via bol_to_prev_bol, so a delta in the
        # fallback counter is a recenter signal. We'll infer below.)
        return result
    ctrl.dpy.find_top = find_top

    # Now run the insert perftest manually so we can stop at 1s and dump stats.
    ctrl.ed.move_end()
    start = time()
    last_fallback_count = stats["bol_to_prev_bol_fallback"]
    last_reanchor_count = stats["reanchor_calls"]
    while time() - start < 1.0:
        ctrl.dpy.paint(ctrl.ed.mark)
        stats["frames"] += 1
        ctrl.ed.insert(ord("a"))
        ctrl.ed.move_backward_char()
        ctrl.dpy.layout.move_backward_line()

    # Heuristic for recenter: find_top calls that consumed a chunk of
    # bol_to_prev_bol fallbacks. The cleaner detection would be patching
    # find_top further; this is the simpler proxy.
    # Actually let's compute differently: recenter does up to preferred_row
    # bol_to_prev_bol calls; sticky does none. So:
    #   recenters ≈ ceil(non-step bol_to_prev_bol fallbacks / preferred_row)
    # But step itself also does bol_to_prev_bol. Tricky to attribute.

    print(f"frames: {stats['frames']}")
    print(f"reanchor_calls: {stats['reanchor_calls']}")
    print(f"  via ensure_bracketed: {stats['ensure_bracketed_reanchor']}")
    print(f"  via bol_to_prev_bol fallback: {stats['bol_to_prev_bol_fallback']}")
    print(f"ensure_bracketed dispositions:")
    print(f"  bracketed: {stats['ensure_bracketed_bracketed']}")
    print(f"  extend:    {stats['ensure_bracketed_extend']}")
    print(f"  reanchor:  {stats['ensure_bracketed_reanchor']}")
    print(f"find_top_calls: {stats['find_top_calls']}")
    print(f"  with top_loc missing from ladder (forced recenter): {stats['top_loc_missing_from_ladder']}")
    print(f"avg ladder len at find_top entry: {sum(stats['ladder_lens'])/max(1,len(stats['ladder_lens'])):.1f}")
    print(f"min/max ladder len: {min(stats['ladder_lens'])}/{max(stats['ladder_lens'])}")


if __name__ == "__main__":
    main()
