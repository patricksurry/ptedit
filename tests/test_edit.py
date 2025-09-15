from ptedit.document import Document
from ptedit.edit import Edit


def test_apply():
    doc = Document('the quick brown fox')
    pt = doc.get_point()
    assert pt.piece.prev is not None
    e1 = Edit(pt.piece.prev, pt.piece, None, None, None)
    e2 = e1.merge_or_append(pt, insert='abc')
    assert e2 != e1
    assert str(doc) == '|abc|^the quick brown fox|'
    e3 = e2.merge_or_append(pt, delete=-2)
    assert str(doc) == '|a|^the quick brown fox|'
    assert e3 == e2
    e4 = e3.merge_or_append(pt, delete=3)
    assert e4 != e3
    doc.set_point(e4.get_change_end())
    assert str(doc) == '|a|^ quick brown fox|'