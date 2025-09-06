import pytest
from ptedit import piecetable
from ptedit.location import Location
from ptedit.piece import PrimaryPiece

doc = piecetable.Document('the quick brown fox')
doc.set_point_start().move_point(4)
doc.insert("f")
doc.insert("astest ")
doc.move_point(-4)
doc.delete(9)


def test_structure():
    assert len(doc) == 18
    assert doc.get_data() == "the fast brown fox"
    assert str(doc) == "|the |fast|^ brown fox|"


def test_unordered():
    p = Location(PrimaryPiece(data='foo'))
    q = Location(PrimaryPiece(data='bar'))
    assert not p.is_at_or_before(q) and not p.is_at_or_after(q) and not q.is_at_or_before(p) and not q.is_at_or_after(p)
    assert p.distance_after(q) is None and p.distance_before(q) is None and q.distance_after(p) is None and q.distance_before(p) is None


def test_ordering():
    doc.set_point_start()
    p0 = doc.get_point()
    p2 = p0.move(2)
    p3 = p0.move(3)
    p15 = p0.move(15)
    p18 = p0.move(18)

    assert p0.is_start()
    assert p18.is_end()
    assert p0.is_at_or_before(p18)
    assert p3.is_at_or_before(p3) and p3.is_at_or_after(p3)
    assert p18.is_at_or_after(p0)
    assert p3.is_at_or_after(p2)
    assert p0.is_at_or_before(p15) and p18.is_at_or_after(p15)
    assert p15.is_at_or_before(p18) and p15.is_at_or_after(p0)

    assert p15.distance_after(p2) == 13
    assert p2.distance_before(p15) == 13
    assert p15.distance_after(p0) == 15
    assert p15.distance_before(p18) == 3


@pytest.mark.parametrize("offset", [
    0, 1, 10, 30, 17, 18, -20, -18, -17, -1
])
def test_location_offset_roundtrip(offset: int):
    (doc.set_point_start() if offset >= 0 else doc.set_point_end()).move_point(offset)
    actual = doc.get_point().position()
    expect = max(min(offset, len(doc)), -len(doc))
    if expect < 0:
        expect += len(doc)
    assert actual == expect


def test_find_char_forward():
    doc.set_point_start().move_point(4)
    assert doc.find_char_forward('fa')
    assert doc.get_char() == 'f'
    assert doc.get_point().position() == 4
    doc.move_point(1)
    assert doc.find_char_forward('xf')
    assert doc.get_char() == 'f'
    assert doc.get_point().position() == 15
    assert not doc.find_char_forward('the')
    assert doc.get_char() == '\0'
    assert doc.get_point().position() == 18


def test_find_char_backward():
    doc.set_point_end()
    assert doc.find_char_backward('f')
    assert doc.get_char() == 'o'
    doc.move_point(-1)
    assert doc.find_char_backward('f')
    assert doc.get_char() == 'a'
    doc.move_point(-1)
    assert not doc.find_char_backward('f')
    assert doc.get_char() == 't'  # failed
    assert doc.at_start()
