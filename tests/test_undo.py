import pytest
from ptedit import piecetable


def test_undo():
    doc = piecetable.PieceTable('the quick brown fox')
    doc.set_point(doc.offset_to_location(4))
    doc.insert("fastest ")
    doc.move_point(-4)
    doc.delete(9)

    doc.undo()

    assert doc.length == 18 + 9
    assert doc.data == "the fastest quick brown fox"

    doc.undo()

    assert doc.length == 19
    assert doc.data == "the quick brown fox"

    doc.redo()
    doc.redo()

    assert doc.length == 18
    assert doc.data == "the fast brown fox"
