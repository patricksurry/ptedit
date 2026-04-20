"""
Characterization tests pinning behavior across the MVC refactor.
These exercise the public API surface (key entry points used by Controller)
so that the refactor is judged green/red purely by these + existing tests.
"""
from ptedit import document, display, editor


def make_dpy(text: str, rows: int = 24, cols: int = 80):
    doc = document.Document(text)
    dpy = display.Display(doc, display.Screen(rows, cols))
    return doc, dpy


def make_editor(text: str, rows: int = 24, cols: int = 80):
    doc = document.Document(text)
    dpy = display.Display(doc, display.Screen(rows, cols))
    ed = editor.Editor(doc, dpy.layout, lambda msg, warn=False: dpy.show_message(msg, warn))
    return doc, dpy, ed


def test_line_start_end_roundtrip():
    """move_end_line then move_start_line returns to BoL of original line."""
    doc, dpy = make_dpy('one two three\nfour five six\n')
    doc.move_point(5)  # 't' of 'two' on first line
    dpy.layout.move_end_line()
    assert doc.get_char() == '\n', f"expected newline at EOL, got {doc.get_char()!r}"
    dpy.layout.move_start_line()
    assert doc.get_point().position() == 0


def test_line_forward_back_preserves_column():
    """
    move_forward_line + move_backward_line round-trip preserves position
    when paint() runs in between to resolve pin_preferred_col.

    The middle line 'a' is shorter than the requested column, so paint()
    must clamp the cursor there.  preferred_col must be preserved across
    that clamp so the surrounding longer lines snap back to column 3.
    A buggy implementation that overwrites preferred_col with the post-clamp
    cursor column would land at column 1 (or 0) of the outer lines instead.
    """
    doc, dpy = make_dpy('three\na\nseven!!\n')
    doc.move_point(3)   # column 3 ('e') of 'three'
    dpy.paint()         # seeds preferred_col=3 from current cursor column
    pt_before = doc.get_point().position()
    assert pt_before == 3
    dpy.layout.move_forward_line()
    dpy.paint()         # on 'a' line; cursor must clamp, preferred_col stays 3
    dpy.layout.move_forward_line()
    dpy.paint()         # on 'seven!!'; should snap to column 3 -> pos 11
    assert doc.get_point().position() == 11
    dpy.layout.move_backward_line()
    dpy.paint()         # back on 'a' line; clamp again, preferred_col stays 3
    dpy.layout.move_backward_line()
    dpy.paint()         # back on 'three'; should restore column 3
    assert doc.get_point().position() == pt_before


def test_status_message_contains_position_and_filename():
    from ptedit.controller import Controller
    doc = document.Document('hello world')
    dpy = display.Display(doc, display.Screen(24, 80), fname='foo.txt')

    class Stub:
        fname = 'foo.txt'
    stub = Stub()
    stub.doc = doc
    stub.dpy = dpy
    s = Controller.status_message(stub, (0, 0))
    assert 'foo.txt' in s
    assert 'pos 0/11' in s
    assert 'lns 0/0' in s


def test_clip_line_roundtrip():
    doc, dpy, ed = make_editor('alpha\nbravo\ncharlie\n')
    doc.move_point(8)  # inside 'bravo'
    ed.cut_line()
    assert ed.clipboard == 'bravo\n'
    assert doc.get_data() == 'alpha\ncharlie\n'
    ed.paste()
    assert doc.get_data() == 'alpha\nbravo\ncharlie\n'


def test_isearch_message_set_on_search():
    doc, dpy, ed = make_editor('the quick brown fox')
    ed.isearch_forward()         # opens isearch
    ed.insert(ord('q'))          # adds to search
    # The display message should reflect the search prompt
    assert 'Search' in dpy.message
