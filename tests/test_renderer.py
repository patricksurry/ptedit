from ptedit import renderer, piecetable
from os import path


ALICE_NL = open(path.join(path.dirname(__file__), 'alice1.asc')).read()


def test_frame():
    alice = piecetable.Document(ALICE_NL)
    alice.set_point(alice.get_start().move(595))
    pt = alice.get_point()
    rdr = renderer.Renderer(alice, renderer.Screen(24, 72))
    rdr.preferred_top = alice.get_end()     # so it won't be found
    rdr.find_top()
    top = alice.get_point()
    s = alice.get_data(top, pt)
    assert s.startswith('conversations in it')


def test_wrap():
    doc = piecetable.Document('the\t quick brown fox\njumps \tover the lazy dog')
    rdr = renderer.Renderer(doc, renderer.Screen(24, 16))
    rdr.bol_to_next_bol()
    assert doc.get_point().position() == 11
    rdr.bol_to_next_bol()
    assert doc.get_point().position() == 21
