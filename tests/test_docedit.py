from ptedit import piecetable


def test_start_end():
    doc = piecetable.Document()
    assert doc.at_start() and doc.at_end()

    doc = piecetable.Document('foobar')
    assert doc.at_start()
    doc.set_point_end()
    assert doc.at_end()
    doc.set_point_start()
    assert doc.at_start()


def test_str():
    doc = piecetable.Document()
    assert str(doc) == "||"
    doc = piecetable.Document('ac')
    assert str(doc) == "|^ac|"
    assert doc.next_char() == 'a'
    assert len(doc.get_point().piece) == 2
    assert doc.get_point().offset == 1
    doc.insert('b')
    assert str(doc) == "|a|b|^c|"


def test_delete_backward():
    doc = piecetable.Document('the quick brown fox')
    assert len(doc.edit_stack) == 0

    doc.move_point(9)
    doc.delete(-1)
    doc.delete(-1)
    assert doc.get_data() == 'the qui brown fox'
    assert len(doc.edit_stack) == 1


def test_delete_forward():
    doc = piecetable.Document('the quick brown fox')
    assert len(doc.edit_stack) == 0

    doc.move_point(4)
    doc.delete(1)
    doc.delete(1)
    assert doc.get_data() == 'the ick brown fox'
    assert len(doc.edit_stack) == 1


def test_insert():
    doc = piecetable.Document('the quick brown fox')
    assert len(doc.edit_stack) == 0

    # check that insert combines
    doc.move_point(100)
    doc.insert(' is')
    doc.insert(' white')
    assert doc.get_data() == 'the quick brown fox is white'
    assert len(doc.edit_stack) == 1


def test_replace():
    doc = piecetable.Document('the quick brown fox')
    assert len(doc.edit_stack) == 0

    doc.delete(2)
    assert doc.get_data() == 'e quick brown fox'
    assert len(doc.edit_stack) == 1

    doc.replace('a')
    assert doc.get_data() == 'a quick brown fox'
    assert len(doc.edit_stack) == 2

    # check that replace combines
    doc.replace('nother')
    assert doc.get_data() == 'another brown fox'
    assert len(doc.edit_stack) == 2

    doc.move_point(2)
    doc.replace('l')
    doc.replace('ack')
    assert doc.get_data() == 'another black fox'
    assert len(doc.edit_stack) == 3

