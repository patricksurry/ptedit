from ptedit.document import Document
from ptedit.edit import Edit


def test_apply():
    doc = Document('the quick brown fox')
    pt = doc.get_point()
    assert pt.piece.prev is not None
    e1 = Edit(pt.piece, pt.piece.prev)
    e2 = e1.apply_change(pt, insert='abc')
    assert e2 != e1
    assert str(doc) == '|abc|^the quick brown fox|'
    e3 = e2.apply_change(pt, delete=-2)
    assert str(doc) == '|a|^the quick brown fox|'
    assert e3 == e2
    e4 = e3.apply_change(pt, delete=3)
    assert e4 != e3
    doc.set_point(e4.get_change_end())
    assert str(doc) == '|a|^ quick brown fox|'


def _roundtrip(doc, action):
    """Apply action then undo + redo, asserting the data round-trips."""
    before = doc.get_data()
    action()
    after = doc.get_data()
    assert before != after
    doc.undo()
    assert doc.get_data() == before
    doc.redo()
    assert doc.get_data() == after


def test_insert_at_start_is_exclude_empty():
    doc = Document('hello')
    doc.set_point_start()
    _roundtrip(doc, lambda: doc.insert('X'))
    assert doc.get_data() == 'Xhello'


def test_insert_at_end_is_exclude_empty():
    doc = Document('hello')
    doc.set_point_end()
    _roundtrip(doc, lambda: doc.insert('X'))
    assert doc.get_data() == 'helloX'


def test_insert_mid_piece_is_exclude_empty():
    doc = Document('hello')
    doc.set_point_start().move_point(2)
    _roundtrip(doc, lambda: doc.insert('X'))
    assert doc.get_data() == 'heXllo'


def test_delete_within_a_piece():
    doc = Document('hello world')
    doc.set_point_start().move_point(5)
    _roundtrip(doc, lambda: doc.delete(-2))
    assert doc.get_data() == 'hel world'


def test_delete_across_pieces():
    """Build a multi-piece chain via two inserts, then delete across the boundary."""
    doc = Document('hello world')
    doc.set_point_start().move_point(5)
    doc.insert(' brave new')              # 'hello brave new world' across pieces
    doc.set_point_start().move_point(4)
    _roundtrip(doc, lambda: doc.delete(8))
    assert doc.get_data() == 'hellnew world'