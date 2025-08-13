import pytest
from ptedit import piecetable

doc = piecetable.PieceTable('the quick brown fox')
doc.set_point(doc.offset_to_location(4))
doc.insert("f")
doc.insert("astest ")
doc.move_point(-4)
doc.delete(9)


def test_structure():
    assert doc.length == 18
    assert doc.data == "the fast brown fox"


@pytest.mark.parametrize("offset", [
    0, 1, 10, 30, 17, 18, -20, -18, -17, -1
])
def test_location_offset_roundtrip(offset):
    loc = doc.offset_to_location(offset)
    actual = doc.location_to_offset(loc)
    expect = max(min(offset, doc.length), -doc.length)
    if expect < 0:
        expect += doc.length
    assert actual == expect


def test_find_char_forward():
    doc.set_point(doc.offset_to_location(4))
    assert doc.find_char_forward('fa').get_char() == 'f'
    assert doc.location_to_offset(doc.get_point()) == 4
    doc.move_point(1)
    assert doc.find_char_forward('xf').get_char() == 'f'
    assert doc.location_to_offset(doc.get_point()) == 15
    assert doc.find_char_forward('the').get_char() == ''
    assert doc.location_to_offset(doc.get_point()) == 18


def test_find_char_backward():
    doc.set_point(doc.get_end())
    assert doc.find_char_backward('f').get_char() == 'o'
    doc.move_point(-1)
    assert doc.find_char_backward('f').get_char() == 'a'
    doc.move_point(-1)
    assert doc.find_char_backward('f').get_char() == 't'  # failed
    assert doc.get_point() == doc.get_start()
