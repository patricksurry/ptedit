import pytest
from ptedit import piecetable
from ptedit.location import Location
from ptedit.piece import PrimaryPiece

doc = piecetable.Document('the quick brown fox')
doc.set_point(doc.get_start().move(4))
doc.insert("f")
doc.insert("astest ")
doc.move_point(-4)
doc.delete(9)


def test_structure():
    assert len(doc) == 18
    assert doc.get_data() == "the fast brown fox"
    assert str(doc) == "||the |fast| brown fox||"


def test_unordered():
    p = Location(PrimaryPiece(data='foo'))
    q = Location(PrimaryPiece(data='bar'))
    assert not p <= q and not q <= p
    assert p - q is None and q - p is None


def test_ordering():
    p0 = doc.get_start()
    p2 = p0.move(2)
    p3 = p0.move(3)
    p15 = p0.move(15)
    p18 = p0.move(18)

    assert p0 == doc.get_start()
    assert p18 == doc.get_end()
    assert p0 < p18
    assert p3 <= p3
    assert p18 >= p0
    assert p3 > p2
    assert p0 < p15 < p18
    assert p18 > p15 > p0

    assert p15 - p2 == 13
    assert p2 - p15 == -13


@pytest.mark.parametrize("offset", [
    0, 1, 10, 30, 17, 18, -20, -18, -17, -1
])
def test_location_offset_roundtrip(offset: int):
    loc = (doc.get_start() if offset >= 0 else doc.get_end()).move(offset)
    actual = loc.position()
    expect = max(min(offset, len(doc)), -len(doc))
    if expect < 0:
        expect += len(doc)
    assert actual == expect


def test_find_char_forward():
    doc.set_point(doc.get_start().move(4))
    assert doc.find_char_forward('fa')
    assert doc.get_char() == 'f'
    assert doc.get_point().position() == 4
    doc.move_point(1)
    assert doc.find_char_forward('xf')
    assert doc.get_char() == 'f'
    assert doc.get_point().position() == 15
    assert not doc.find_char_forward('the')
    assert doc.get_char() == ''
    assert doc.get_point().position() == 18


def test_find_char_backward():
    doc.set_point(doc.get_end())
    assert doc.find_char_backward('f')
    assert doc.get_char() == 'o'
    doc.move_point(-1)
    assert doc.find_char_backward('f')
    assert doc.get_char() == 'a'
    doc.move_point(-1)
    assert not doc.find_char_backward('f')
    assert doc.get_char() == 't'  # failed
    assert doc.get_point() == doc.get_start()
