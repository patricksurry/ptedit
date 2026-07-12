from ptedit import piece
from ptedit.location import Location
from ptedit.piece import PrimaryPiece


def test_primary():
    p = piece.PrimaryPiece(data='foo')
    assert p.data == 'foo'
    p.extend('bar')
    assert p.data == 'foobar'
    assert len(p) == 6


def test_secondary():
    foobar = piece.PrimaryPiece(data='foobar')

    p = piece.SecondaryPiece(prev=foobar, source=foobar, start=2, length=3)
    assert p.prev == foobar
    assert p.data == 'oba'
    p.trim(1).trim(-1)
    assert p.data == 'b'


def test_piece_equality_is_identity():
    a = PrimaryPiece(data='abc')
    b = PrimaryPiece(data='abc')
    assert a == a and a != b
    assert Location(a, 1) == Location(a, 1)
    assert Location(a, 1) != Location(b, 1)
