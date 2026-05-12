from ptedit import display, document
from os import path


ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()
ALICE_FLOW = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()


def test_frame():
    alice = document.Document(ALICE_NL)
    alice.set_point_start().move_point(595)
    pt = alice.get_point()
    dpy = display.Display(alice, display.Screen(24, 72))
    dpy.find_top()           # preferred_top no longer exists
    top = alice.get_point()
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
    doc = document.Document(ALICE_FLOW)
    dpy = display.Display(doc, display.Screen(24, 80))
    doc.move_point(10)
    dpy.paint()
    assert dpy.layout.preferred_col == 10

    pt = doc.get_point()
    while not doc.at_end():
        dpy.layout.move_forward_line()
        dpy.paint()
        assert doc.get_point() != pt
        pt = doc.get_point()

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
    centered_top = dpy.top_pos
    # move the cursor down a few lines (stays within the window, sticky top holds)
    for _ in range(3):
        dpy.layout.move_forward_line()
        dpy.paint()
    # top should still be the sticky one (cursor hasn't left the window)
    assert dpy.top_pos == centered_top
    # now Ctrl-L: should force a recenter so the cursor is back near preferred_row
    dpy.recenter()
    assert dpy.top_pos != centered_top  # top moved to re-center on the new cursor


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
