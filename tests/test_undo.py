from ptedit import piecetable


def test_undo():
    doc = piecetable.Document('the quick brown fox')
    doc.set_point(doc.get_start().move(4))
    doc.insert("fastest ")
    doc.move_point(-4)
    doc.delete(9)

    doc.undo()
    pt = doc.get_point()
    assert pt.is_at_or_after(doc.get_start()) and pt.is_at_or_before(doc.get_end())

    assert len(doc) == 18 + 9
    assert doc.get_data() == "the fastest quick brown fox"

    doc.undo()

    assert len(doc) == 19
    assert doc.get_data() == "the quick brown fox"

    doc.redo()
    doc.redo()

    assert len(doc) == 18
    assert doc.get_data() == "the fast brown fox"
