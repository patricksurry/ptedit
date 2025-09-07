from ptedit import document


def test_undo():
    doc = document.Document('the quick brown fox')
    doc.set_point_start().move_point(4)
    doc.insert("fastest ")
    assert str(doc) == '|the |fastest |^quick brown fox|'
    doc.move_point(-4)
    doc.delete(9)
    assert str(doc) == '|the |fast|^ brown fox|'
    doc.undo()

    pt = doc.get_point()
    assert pt.is_at_or_after(doc.set_point_start().get_point()) and pt.is_at_or_before(doc.set_point_end().get_point())
    doc.set_point(pt)
    assert len(doc) == 18 + 9
    assert str(doc) == '|the |fastest |quick^ brown fox|'

    doc.undo()
    assert len(doc) == 19
    assert str(doc) == "|the ^quick brown fox|"

    doc.redo()
    doc.redo()

    assert len(doc) == 18
    assert str(doc) == '|the |fast|^ brown fox|'
