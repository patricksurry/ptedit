"""
Correctness tests for preserving ladder[0] across simple edits.

Strategy: build two displays from the same document state, do an edit
on one, then compare its paint() output against a freshly-constructed
display whose ladder is empty.  Any divergence means the cached ladder
is stale.

These tests will fail today (the change_handler unconditionally
invalidates the entire ladder, so the post-edit ladder is correctly
empty and gets rebuilt — there's no stale state to expose).  They
exist to pin behavior once we start preserving the prefix.
"""

from ptedit import display, document


class RecordingScreen(display.Screen):
    """Records every put() in order; compare lists for paint equivalence."""
    def __init__(self, height: int, width: int):
        super().__init__(height, width)
        self.cells: list[tuple[int, bool]] = []

    def clear(self):
        self.cells = []

    def put(self, ch: int, highlight: bool = False):
        self.cells.append((ch, highlight))


def make_dpy(text: str, point: int = 0, rows: int = 8, cols: int = 16):
    """rows = Display.rows (usable text area).  Screen height is rows + 1
    to leave room for the status line that Display reserves."""
    doc = document.Document(text)
    doc.set_point_start().move_point(point)
    dpy = display.Display(doc, RecordingScreen(rows + 1, cols))
    return doc, dpy


def fresh_paint(text: str, point: int, rows: int, cols: int):
    """Build a brand-new Display at the given point and return paint cells."""
    doc, dpy = make_dpy(text, point, rows, cols)
    dpy.paint()
    return dpy.scr.cells, doc.get_point().position()


def assert_paint_matches_fresh(dpy, doc, label: str = ""):
    """The current Display's next paint must match what a fresh Display would paint."""
    text = doc.get_data()
    pt = doc.get_point().position()
    expected_cells, expected_pt = fresh_paint(text, pt, dpy.rows, dpy.cols)
    dpy.scr.clear()
    dpy.paint()
    assert doc.get_point().position() == expected_pt, (
        f"{label}: point drifted, got {doc.get_point().position()} expected {expected_pt}"
    )
    assert dpy.scr.cells == expected_cells, (
        f"{label}: paint output diverged from fresh"
    )


# ---------------------------------------------------------------------------
# T1.  Edit in a piece different from ladder[0] keeps ladder[0] valid.
# ---------------------------------------------------------------------------

def test_insert_below_ladder0_does_not_break_paint():
    text = "alpha\nbravo\ncharlie\ndelta\necho\nfoxtrot\ngolf\nhotel\n"
    doc, dpy = make_dpy(text, point=len("alpha\nbravo\ncharlie\n") + 2)  # in 'delta'
    dpy.paint()
    # Now edit further down the doc (a different piece after the splits done by paint).
    doc.set_point_end().move_point(-3)            # inside 'hotel'
    doc.insert("X")
    # Restore point near the original to mimic what an interactive session does.
    doc.set_point_start().move_point(len("alpha\nbravo\ncharlie\n") + 2)
    assert_paint_matches_fresh(dpy, doc, "insert below ladder[0]")


def test_delete_below_ladder0_does_not_break_paint():
    text = "alpha\nbravo\ncharlie\ndelta\necho\nfoxtrot\ngolf\nhotel\n"
    doc, dpy = make_dpy(text, point=len("alpha\nbravo\ncharlie\n") + 2)
    dpy.paint()
    doc.set_point_end().move_point(-3)
    doc.delete(1)
    doc.set_point_start().move_point(len("alpha\nbravo\ncharlie\n") + 2)
    assert_paint_matches_fresh(dpy, doc, "delete below ladder[0]")


# ---------------------------------------------------------------------------
# T2.  Pure insert at a piece boundary leaves all pieces intact;
#      no remap is required.
# ---------------------------------------------------------------------------

def test_insert_at_piece_boundary_does_not_break_paint():
    text = "first\nsecond\nthird\nfourth\nfifth\n"
    doc, dpy = make_dpy(text, point=0)
    dpy.paint()
    # Force a piece split somewhere by doing an interior insert.
    doc.move_point(3)
    doc.insert("Z")
    # Now do another insert exactly at the boundary of the previously-created
    # piece (this is a "pure insert at boundary" — no further split).
    doc.set_point_start().move_point(4)           # right after the inserted Z
    doc.insert("Q")
    assert_paint_matches_fresh(dpy, doc, "insert at piece boundary")


# ---------------------------------------------------------------------------
# T3.  Insert mid-piece on the topmost visible line — ladder[0] is in the
#      same piece as the change.
# ---------------------------------------------------------------------------

def test_insert_on_first_visible_line_does_not_break_paint():
    text = "topline_with_some_text\nsecond\nthird\n"
    doc, dpy = make_dpy(text, point=5)            # mid 'topline...'
    dpy.paint()
    doc.set_point_start().move_point(8)           # still on top line
    doc.insert("Y")
    assert_paint_matches_fresh(dpy, doc, "insert mid first visible line")


# ---------------------------------------------------------------------------
# T4.  Long line that wraps; the wrap point shifts when a space is added or
#      removed.  Critical edge case: ladder[0] could be the *old* wrap
#      position which is no longer a real BoL after the edit.
# ---------------------------------------------------------------------------

def test_remove_space_on_wrapped_first_line_does_not_break_paint():
    # cols=16, build a single line that wraps; the wrap break is on the
    # last space that fits.  Removing a leading character shifts the wrap.
    line = "aaa bbb ccc ddd eee fff ggg hhh"
    text = line + "\nlast\n"
    doc, dpy = make_dpy(text, point=18, rows=4, cols=16)  # cursor on second wrap fragment
    dpy.paint()
    # Delete a character from the *first* wrap fragment, shifting the wrap.
    doc.set_point_start().move_point(2)
    doc.delete(1)
    # Cursor is now at position 17, still on the second wrap fragment of the
    # (modified) line.  ladder[0] (start of cursor's wrap fragment) is now
    # potentially stale — its old position is no longer a wrap break.
    assert_paint_matches_fresh(dpy, doc, "delete shifts wrap on first line")


def test_insert_space_on_wrapped_first_line_does_not_break_paint():
    line = "aaa bbb ccc ddd eee fff ggg hhh"
    text = line + "\nlast\n"
    doc, dpy = make_dpy(text, point=20, rows=4, cols=16)
    dpy.paint()
    doc.set_point_start().move_point(2)
    doc.insert(" ")            # extra space pushes wrap earlier
    assert_paint_matches_fresh(dpy, doc, "insert space shifts wrap on first line")


# ---------------------------------------------------------------------------
# T5.  Backward-delete that removes the newline ending ladder[0]'s line.
#      ladder[0] was a real BoL but the previous line is now merged into it.
# ---------------------------------------------------------------------------

def test_delete_newline_above_top_line_does_not_break_paint():
    text = "above\ntopline\nmiddle\nlast\n"
    # Display chosen so 'topline' starts at the top of screen.
    doc, dpy = make_dpy(text, point=len("above\n") + 3, rows=3, cols=16)  # mid topline
    dpy.paint()
    # Delete the '\n' joining 'above' and 'topline'.
    doc.set_point_start().move_point(len("above"))
    doc.delete(1)
    # Cursor now sits at the join.  After paint, the "first visible line"
    # should reflect the merged line.
    assert_paint_matches_fresh(dpy, doc, "delete newline above top line")


# ---------------------------------------------------------------------------
# T6.  Sanity: a series of inserts on the same line keeps paint output
#      consistent.  This is the tight insert-loop case the perftest covers.
# ---------------------------------------------------------------------------

def test_repeated_inserts_on_one_line_stay_consistent():
    text = "alpha\nbravo\ncharlie\ndelta\necho\n"
    doc, dpy = make_dpy(text, point=len("alpha\nbravo\nchar"), rows=4, cols=16)
    dpy.paint()
    for _ in range(8):
        doc.insert("x")
    assert_paint_matches_fresh(dpy, doc, "repeated inserts on one line")
