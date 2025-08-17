from os import path

from ptedit import piecetable


alice = open(path.join(path.dirname(__file__), 'alice1.asc')).read()


def test_search_forward():
    doc = piecetable.PieceTable(alice)
    assert doc.find_forward('Alice').get_point().position() == 5
    assert doc.find_forward('Alice').get_point().position() == 265
    assert doc.find_forward('Alice').get_point().position() == 656
    assert doc.find_forward('abracadabra').get_point() == doc.get_end()


def test_search_backward():
    doc = piecetable.PieceTable(alice).move_point(655)
    assert doc.find_backward('Alice').get_point().position() == 265
    assert doc.find_backward('Alice').get_point().position() == 5
    assert doc.find_backward('Alice').get_point() == doc.get_start()
