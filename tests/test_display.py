from ptedit import display, document
from os import path


ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()
ALICE_FLOW = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()


def test_frame():
    alice = document.Document(ALICE_NL)
    alice.set_point_start().move_point(595)
    pt = alice.get_point()
    dpy = display.Display(alice, display.Screen(24, 72))
    top_idx, _ = dpy.find_top()      # find_top no longer moves the doc's point
    top = dpy.layout.bol(top_idx)
    s = alice.get_data(top, pt)
    assert s.startswith('the book her sister was reading')


def test_wrap():
    doc = document.Document('the\t quick brown fox\njumps \tover the lazy dog')
    dpy = display.Display(doc, display.Screen(24, 16))
    dpy.layout.move_forward_line()
    assert doc.get_point().position() == 11
    dpy.layout.move_forward_line()
    assert doc.get_point().position() == 21


def test_preferred_col():
    """goal_col now lives on Layout, set eagerly by the first vertical move
    (not by paint) and preserved across many lines of forward/backward
    movement (it only resets at the start/end-of-document boundary)."""
    doc = document.Document(ALICE_FLOW)
    dpy = display.Display(doc, display.Screen(24, 80))
    doc.move_point(10)
    pt = doc.get_point()

    while not doc.at_end():
        dpy.layout.move_forward_line()
        dpy.paint()
        assert doc.get_point() != pt
        pt = doc.get_point()
    assert dpy.layout.goal_col == 10

    while not doc.at_start():
        dpy.layout.move_backward_line()
        dpy.paint()
        assert doc.get_point() != pt, f"failed at {pt.position()}"
        pt = doc.get_point()


def test_paint():
    doc = document.Document(ALICE_FLOW)
    dpy = display.Display(doc, display.Screen(24, 80))
    dpy.paint()

    # forward page+
    for _ in range(32):
        dpy.layout.move_forward_line()
    dpy.paint()

    doc.set_point_end()
    dpy.paint()

    # backward page+
    for _ in range(32):
        dpy.layout.move_backward_line()
    dpy.paint()

    doc.set_point_end()
    dpy.paint()


def test_end():
    doc = document.Document(ALICE_FLOW)
    doc.set_point_end()

    dpy = display.Display(doc, display.Screen(24, 80))
    dpy.paint()
    doc.move_point(-1)
    dpy.layout.move_backward_line()

    assert not doc.at_end()
    dpy.paint()
    assert not doc.at_end()


def test_raw():
    doc = document.Document(open('tests/raw.dat', encoding='iso-8859-1').read())
    dpy = display.Display(doc, display.Screen(24, 80))
    dpy.paint()


def test_recenter():
    doc = document.Document(ALICE_FLOW)
    dpy = display.Display(doc, display.Screen(24, 80))
    # paint somewhere mid-doc, then scroll the cursor within the window
    doc.set_point_start().move_point(4000)
    dpy.paint()
    centered_top = dpy.top_loc
    # move the cursor down a few lines (stays within the window, sticky top holds)
    for _ in range(3):
        dpy.layout.move_forward_line()
        dpy.paint()
    # top should still be the sticky one (cursor hasn't left the window)
    assert dpy.top_loc == centered_top
    # now Ctrl-L: should force a recenter so the cursor is back near preferred_row
    dpy.recenter()
    dpy.paint()
    assert dpy.top_loc != centered_top  # top moved to re-center on the new cursor


class _RecordingScreen(display.Screen):
    """Minimal recording screen that counts put() calls."""
    def __init__(self, height: int, width: int):
        super().__init__(height, width)
        self.events: list[tuple[int, bool]] = []

    def put(self, ch: int, highlight: bool = False):
        self.events.append((ch, highlight))


def test_no_scroll_emits_nothing():
    """The no-scroll fast path must emit zero put() calls."""
    doc = document.Document(ALICE_FLOW)
    scr = _RecordingScreen(24, 80)
    dpy = display.Display(doc, scr)
    doc.set_point_start().move_point(4000)
    dpy.paint()                          # initial full redraw
    n_after_full = len(scr.events)
    dpy.layout.move_forward_line()       # small move, no scroll, no selection
    dpy.paint()
    assert len(scr.events) == n_after_full, (
        f"no-scroll paint should emit zero puts, "
        f"but got {len(scr.events) - n_after_full} extra events"
    )


def test_guard_zone_scroll_redraws():
    """REGRESSION: cursor entering the guard zone must scroll AND redraw.

    There was a bug where `find_top` returned `recentered=False` whenever it
    took the sticky branch — but the sticky branch can change `top_idx` via
    the guard-zone scroll. `paint` then classified `no_scroll` and emitted
    zero puts, leaving the screen stale. This test pushes the cursor into
    the bottom guard zone and asserts that (a) `top_loc` moved and (b) cells
    were re-emitted (the buggy code emitted zero puts).
    """
    doc = document.Document(ALICE_FLOW)
    scr = _RecordingScreen(24, 80)
    dpy = display.Display(doc, scr)
    doc.set_point_start().move_point(4000)
    dpy.paint()                                # initial full redraw
    initial_top = dpy.top_loc
    initial_events = len(scr.events)

    # Comfort zone is delta ∈ [guard_rows, rows - guard_rows - 1].
    # After the initial paint cursor is at delta == preferred_row;
    # push it past the bottom of the comfort zone.
    extra = (dpy.rows - dpy.guard_rows) - dpy.preferred_row + 1
    for _ in range(extra):
        dpy.layout.move_forward_line()
    dpy.paint()

    assert dpy.top_loc != initial_top, (
        "top should have scrolled when cursor entered the bottom guard zone"
    )
    assert len(scr.events) - initial_events > 0, (
        "guard-zone scroll must re-emit cells (regression for the "
        "'top changed but emitted nothing' bug)"
    )


def test_selection_renders_highlighted_region():
    """A paint with mark != point must produce highlighted cells, and a
    subsequent no-scroll paint with the selection still active must
    re-render (fall back to full) rather than the zero-put fast path."""
    doc = document.Document(ALICE_FLOW)
    scr = _RecordingScreen(24, 80)
    dpy = display.Display(doc, scr)
    doc.set_point_start().move_point(4000)
    mark = doc.get_point()                     # mark at 4000
    doc.move_point(40)                         # point at 4040 — selection spans ~half a row
    dpy.paint(mark=mark)

    highlighted = sum(1 for _ch, hi in scr.events if hi)
    assert highlighted > 0, "selection should produce highlighted cells"

    # Move cursor one line down: stays in the comfort zone → no scroll,
    # but mark != point still → no_scroll-with-selection branch should
    # re-render the window (not take the zero-put fast path).
    n_before = len(scr.events)
    dpy.layout.move_forward_line()
    dpy.paint(mark=mark)
    assert len(scr.events) - n_before > 0, (
        "no_scroll paint with an active selection must re-render the window"
    )


def test_bol_to_prev_bol_at_doc_start_is_noop():
    """bol_to_prev_bol at doc start is a no-op (covers the at_start early return)."""
    doc = document.Document(ALICE_FLOW)
    dpy = display.Display(doc, display.Screen(24, 80))
    doc.set_point_start()
    pos_before = doc.get_point().position()
    dpy.layout.bol_to_prev_bol()
    assert doc.get_point().position() == pos_before


def test_change_handler_walks_multi_piece_unlinked_chain():
    """Coverage: an edit that unlinks more than one piece exercises the
    chain-walk in `Layout.change_handler` (`p = p.next`)."""
    doc = document.Document('one\ntwo\nthree\nfour\nfive\n')
    dpy = display.Display(doc, display.Screen(24, 80))
    dpy.paint()
    # Insert in two different middle pieces so the chain has multiple links.
    doc.set_point_start().move_point(5)
    doc.insert('A')
    dpy.paint()
    doc.set_point_start().move_point(12)
    doc.insert('B')
    dpy.paint()
    # Now do a delete that spans both inserts → unlinks multiple pieces.
    doc.set_point_start().move_point(4)
    doc.delete(10)
    dpy.paint()
    # Nothing to assert beyond "didn't blow up" — this exists to exercise the
    # chain-walk branch. The fact that the paint succeeded means the ladder
    # was correctly truncated.


def test_local_edit_renders_tail_only():
    """An edit in the middle of the screen re-renders only the tail rows.

    A fresh document is one big piece, so the first insert at position 4000
    splits that piece and unlinks it — invalidating all ladder entries, which
    forces a 'full' repaint.  We repaint after the first insert to re-establish
    the ladder over the now-fragmented piece table.  The second insert is
    *compatible* (extends the existing ins piece) so it only invalidates by
    position, leaving entries above the edit intact → 'local_edit' fast path.
    """
    doc = document.Document(ALICE_FLOW)
    scr = _RecordingScreen(24, 80)
    dpy = display.Display(doc, scr)
    doc.set_point_start().move_point(4000)   # somewhere mid-doc, mid-screen
    dpy.paint()                              # full redraw — establishes top anchor
    doc.insert('x')                          # first insert: splits the big piece
    dpy.paint()                              # full repaint: ladder now over 2 pieces
    n0 = len(scr.events)                     # baseline after ladder is fragmented
    doc.insert('y')                          # second insert: compatible, position-only truncation
    dpy.paint()
    n1 = len(scr.events) - n0
    full = 23 * 80                           # rows * cols puts for a full render
    # The edit is mid-screen, so the tail render is strictly fewer puts than a
    # full redraw (rows above the edit are left untouched on screen).
    assert 0 < n1 < full, (
        f"local edit should re-render only the tail, got {n1} puts vs {full} full"
    )


class GridScreen(display.Screen):
    """Accumulates a char+highlight grid like memory-mapped video RAM."""
    def __init__(self, height: int, width: int):
        super().__init__(height, width)
        self.clear()

    def clear(self):
        self.hi = [[False] * self.width for _ in range(self.height)]
        self.row = self.col = 0

    def move(self, row: int, col: int):
        self.row, self.col = row, col

    def put(self, ch: int, highlight: bool = False):
        if self.row < self.height:
            self.hi[self.row][self.col] = highlight
        self.col += 1
        if self.col >= self.width:
            self.col = 0
            self.row += 1

    def highlight_count(self) -> int:
        return sum(sum(row) for row in self.hi)


def test_clearing_mark_erases_highlight():
    """A cleared selection must not leave stale highlight on a stable window."""
    doc = document.Document('hello world ' * 40)
    scr = GridScreen(24, 80)
    dpy = display.Display(doc, scr)
    dpy.paint(None)
    mark = doc.get_point()
    doc.move_point(40)
    dpy.paint(mark)
    assert scr.highlight_count() == 40
    dpy.paint(None)                     # mark cleared; window otherwise stable
    assert scr.highlight_count() == 0
