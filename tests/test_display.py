from ptedit import piecetable, display
from os import path

ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()

def test_frame():
    alice = piecetable.PieceTable(ALICE_NL)
    alice.set_point(alice.offset_to_location(595))
    win = display.Display(alice, 24, 40)
    start = win.frame_point(alice.get_start())[0]

    assert alice.slice(start, alice.get_point())[:8] == '"without'

def test_wrap():
    doc = piecetable.PieceTable('the\t quick brown fox\njumps \tover the lazy dog')
    win = display.Display(doc, 24, 16)
    win.next_wrap()
    assert doc.location_to_offset(doc.get_point()) == 11
    win.next_wrap()
    assert doc.location_to_offset(doc.get_point()) == 21
