from ptedit import piecetable, display
from os import path

ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()

def test_frame():
    alice = piecetable.PieceTable(ALICE_NL)
    alice.set_point(alice.offset_to_location(595))
    win = display.Display(alice)
    start = win.mark_frame(alice.offset_to_location(0))

    assert alice.slice(start, alice.get_point())[:8] == '"without'

def test_wrap():
    doc = piecetable.PieceTable('the\t quick brown fox\njumps \tover the lazy dog')
    win = display.Display(doc)
    win.wrap_line(width=16, start=True)
    for start, end in zip(win.breaks[:-1], win.breaks[1:]):
        doc.set_point(doc.offset_to_location(start))
        print(doc.get_string(end-start))
    assert win.breaks == [0, 11, 21]