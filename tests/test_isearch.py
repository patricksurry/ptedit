from os import path

from ptedit import document


alice = open(path.join(path.dirname(__file__), 'alice1.asc')).read()


def test_search_forward():
    doc = document.Document(alice)
    assert doc.find_forward('Alice', document.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 5
    assert doc.find_forward('Alice', document.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 265
    assert doc.find_forward('Alice', document.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 656
    assert not doc.find_forward('abracadabra', document.MatchMode.EXACT_CASE)
    assert doc.at_end()


def test_search_backward():
    doc = document.Document(alice).move_point(655)
    assert doc.find_backward('Alice', document.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 265
    assert doc.find_backward('Alice', document.MatchMode.EXACT_CASE)
    assert doc.get_point().position() == 5
    assert doc.find_backward('Alice', document.MatchMode.EXACT_CASE)
    assert doc.at_start()
