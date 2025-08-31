from ptedit import display, piecetable
from os import path


ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()
ALICE_FLOW = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()


def test_frame():
    alice = piecetable.Document(ALICE_NL)
    alice.set_point(alice.get_start().move(595))
    pt = alice.get_point()
    dpy = display.Display(alice, display.Screen(24, 72))
    dpy.preferred_top = alice.get_end()     # so it won't be found
    dpy.find_top()
    top = alice.get_point()
    s = alice.get_data(top, pt)
    assert s.startswith('conversations in it')


def test_wrap():
    doc = piecetable.Document('the\t quick brown fox\njumps \tover the lazy dog')
    dpy = display.Display(doc, display.Screen(24, 16))
    dpy.move_forward_line()
    assert doc.get_point().position() == 11
    dpy.move_forward_line()
    assert doc.get_point().position() == 21


def test_paint():
    doc = piecetable.Document(ALICE_FLOW)
    dpy = display.Display(doc, display.Screen(24, 80))
    dpy.paint()

    # forward page+
    for _ in range(32):
        dpy.move_forward_line()
    dpy.paint()

    doc.set_point(doc.get_end())
    dpy.paint()

    # backward page+
    for _ in range(32):
        dpy.move_backward_line()
    dpy.paint()

    doc.set_point(doc.get_start())
    dpy.paint()


def test_end():
    doc = piecetable.Document(ALICE_FLOW)
    doc.set_point(doc.get_end())

    dpy = display.Display(doc, display.Screen(24, 80))
    dpy.paint()
    doc.move_point(-1)
    dpy.move_backward_line()

    assert not doc.at_end()
    dpy.paint()
    assert not doc.at_end()
