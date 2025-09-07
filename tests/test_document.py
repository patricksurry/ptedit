from ptedit import document


def test_start_end():
    doc = document.Document()
    assert doc.at_start() and doc.at_end()

    doc = document.Document('foobar')
    assert doc.at_start()
    assert str(doc) == '|^foobar|'
    doc.set_point_end()
    assert doc.at_end()
    assert str(doc) == '|foobar|^'
    doc.set_point_start()
    assert doc.at_start()
    assert str(doc) == '|^foobar|'


def test_str():
    doc = document.Document()
    assert str(doc) == "|^"
    doc = document.Document('ac')
    assert str(doc) == "|^ac|"
    assert doc.next_char() == 'a'
    assert len(doc.get_point().piece) == 2
    assert doc.get_point().offset == 1
    doc.insert('b')
    assert str(doc) == "|a|b|^c|"


def test_delete_backward():
    doc = document.Document('the quick brown fox')
    assert doc.edit_counts()[0] == 1

    doc.move_point(9)
    doc.delete(-1)
    doc.delete(-1)
    assert str(doc) == '|the qui|^ brown fox|'
    assert doc.edit_counts()[0] == 2


def test_delete_forward():
    doc = document.Document('the quick brown fox')
    assert doc.edit_counts()[0] == 1

    doc.move_point(4)
    doc.delete(1)
    doc.delete(1)
    assert str(doc) == '|the |^ick brown fox|'
    assert doc.edit_counts()[0] == 2


def test_insert():
    doc = document.Document('the quick brown fox')
    assert doc.edit_counts()[0] == 1

    # check that insert combines
    doc.move_point(9)
    doc.insert(' white')
    doc.insert(' sly')
    assert str(doc) == '|the quick| white sly|^ brown fox|'
    assert doc.edit_counts()[0] == 2


def test_replace():
    doc = document.Document('the quick brown fox')
    assert doc.edit_counts()[0] == 1

    doc.move_point(1)
    doc.delete(2)
    assert str(doc) == '|t|^ quick brown fox|'
    assert doc.edit_counts()[0] == 2

    doc.move_point(-1)
    doc.replace('a')
    assert str(doc) == '|a|^ quick brown fox|'
    assert doc.edit_counts()[0] == 3

    #TODO why doesn't this replace combine?
    doc.replace('nother')
    assert str(doc) == '|a|nother|^ brown fox|'
    assert doc.edit_counts()[0] == 4

    # these replaces do combine
    doc.move_point(2)
    doc.replace('l')
    doc.replace('ack')
    assert str(doc) == '|a|nother| b|lack|^ fox|'
    assert doc.edit_counts()[0] == 5

