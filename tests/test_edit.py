from ptedit import piecetable


def test_str():
    doc = piecetable.PieceTable()
    assert str(doc) == "|||"
    doc = piecetable.PieceTable('ac')
    assert str(doc) == "||ac||"
    doc.next_char()
    doc.insert('b')
    assert str(doc) == "||a|b|c||"


def test_delete():
    doc = piecetable.PieceTable('the quick brown fox')
    doc.set_point(doc.offset_to_location(9))
    doc.delete(-1)
    doc.delete(-1)
    assert doc.data == 'the qui brown fox'


def test_replace():
    doc = piecetable.PieceTable('the quick brown fox')
    assert len(doc.edit_stack) == 0

    doc.delete(2)
    assert doc.data == 'e quick brown fox'
    assert len(doc.edit_stack) == 1

    doc.replace('a')
    assert doc.data == 'a quick brown fox'
    assert len(doc.edit_stack) == 2

    # check that replace combines
    doc.replace('nother')
    assert doc.data == 'another brown fox'
    assert len(doc.edit_stack) == 2

    doc.move_point(2)
    doc.replace('l')
    doc.replace('ack')
    assert doc.data == 'another black fox'
    assert len(doc.edit_stack) == 3

    # check that insert combines
    doc.move_point(100)
    doc.insert(' is')
    doc.insert(' white')
    assert doc.data == 'another black fox is white'
    assert len(doc.edit_stack) == 4
