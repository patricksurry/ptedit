from ptedit import controller, piecetable, location
from os import path


ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()


def test_frame():
    alice = piecetable.PieceTable(ALICE_NL)
    alice.set_point(alice.get_start().move(595))
    pt = alice.get_point()
    win = controller.Controller(alice, 24, 72)
    win.find_top(alice.get_end())
    top = alice.get_point()
    s = location.Location.span_data(top, pt)
    assert s.startswith('the book her sister')


def test_wrap():
    doc = piecetable.PieceTable('the\t quick brown fox\njumps \tover the lazy dog')
    win = controller.Controller(doc, 24, 16)
    win.bol_to_next_bol()
    assert doc.get_point().position() == 11
    win.bol_to_next_bol()
    assert doc.get_point().position() == 21
