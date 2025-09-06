from ptedit.piecetable import Document
from ptedit.editstack import Edit


def test_apply():
    doc = Document('the quick brown fox')
    pt = doc.get_point()
    assert pt.piece.prev is not None
    e1 = Edit(pt.piece.prev, pt.piece, None, None, None)
    e2 = e1.apply(pt, insert='abc')
    assert e2 == e1
    assert str(doc) == '|abc|^the quick brown fox|'
    e3 = e2.apply(pt, delete=-2)
    assert e3 == e2
    assert str(doc) == '|a|^the quick brown fox|'
    e4 = e3.apply(pt, delete=3)
    assert e4 != e3
    doc.set_point(e4.get_end())
    assert str(doc) == '|a|^ quick brown fox|'