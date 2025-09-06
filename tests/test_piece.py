from ptedit import piece


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
