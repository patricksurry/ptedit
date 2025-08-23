from os import path

from ptedit import piecetable


alice = open(path.join(path.dirname(__file__), 'alice1.asc')).read()


def test_search_forward():
    doc = piecetable.Document(alice)
    assert doc.find_forward('Alice', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 5
    assert doc.find_forward('Alice', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 265
    assert doc.find_forward('Alice', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 656
    assert not doc.find_forward('abracadabra', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point() == doc.get_end()


def test_search_backward():
    doc = piecetable.Document(alice).move_point(655)
    assert doc.find_backward('Alice', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 265
    assert doc.find_backward('Alice', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 5
    assert doc.find_backward('Alice', piecetable.MatchMode.EXACT_CASE)
    assert doc.get_point() == doc.get_start()
