from ptedit import controller, piecetable, location
from os import path

ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()

def test_frame():
    alice = piecetable.PieceTable(ALICE_NL)
    alice.set_point(alice.get_start().move(595))
    win = controller.Controller(alice, 24, 80)
    start = win.frame_point(alice.get_end())[0]

    assert location.Location.span_data(start, alice.get_point())[:8] == '"without'

def test_wrap():
    doc = piecetable.PieceTable('the\t quick brown fox\njumps \tover the lazy dog')
    win = controller.Controller(doc, 24, 16)
    win.next_wrap()
    assert doc.get_point().position() == 11
    win.next_wrap()
    assert doc.get_point().position() == 21
