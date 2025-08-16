from ptedit import piecetable
from ptedit import location


def test_undo():
    doc = piecetable.PieceTable('the quick brown fox')
    doc.set_point(doc.get_start().move(4))
    doc.insert("fastest ")
    doc.move_point(-4)
    doc.delete(9)

    doc.undo()
    assert location.Location.span_contains(doc.get_point(), doc.get_start(), doc.get_end())

    assert doc.length == 18 + 9
    assert doc.data == "the fastest quick brown fox"

    doc.undo()

    assert doc.length == 19
    assert doc.data == "the quick brown fox"

    doc.redo()
    doc.redo()

    assert doc.length == 18
    assert doc.data == "the fast brown fox"
