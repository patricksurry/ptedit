from __future__ import annotations
from typing import ClassVar, Self
from dataclasses import dataclass


def snippet(s: str, n: int=8):
    return f"'{s}'" if len(s) <= n else f"'{s[:n-2]}...'"


@dataclass(kw_only=True)
class Piece:
    """
    A Piece represents a span of text in the document.
    Some pieces own data, and others point to data held elsewhere.
    The document is a doubly linked list of Pieces.
    """
    _id: ClassVar[int] = 0
    prev: Piece | None = None
    next: Piece | None = None
    _len: int = 0

    id: int = 0             # for debugging it's useful to enumerate pieces

    @property
    def data(self) -> str:
        ...

    def __bool__(self) -> bool:
        # Make any non-None instance is truthy
        # otherwise "if piece ..." checks for len() > 0
        return True

    def __len__(self) -> int:
        return self._len

    def _ref(self) -> tuple[PrimaryPiece, int]:
        ...

    def __post_init__(self):
        """Number pieces sequentially for debugging"""
        self.id = Piece._id
        Piece._id += 1

    def trim(self, n: int) -> Self:
        """
        Trim piece by abs(n) charactesr on the left if n > 0 else on the right"""
        ...

    def lsplit(self, offset: int) -> SecondaryPiece:
        """
        Split a piece at an internal boundary, returning the left piece.
        The piece is linked back *to* its existing neighbor, but
        the link *from* that neighbor isn't changed.  The internal link is empty.
        """
        assert 0 < offset < len(self)
        src, start = self._ref()
        return SecondaryPiece(
            prev=self.prev,
            length=offset,
            source=src,
            start=start,
        )

    def rsplit(self, offset: int) -> SecondaryPiece:
        """
        Return the right hand pice of a split.
        """
        assert 0 < offset < len(self)
        src, start = self._ref()
        return SecondaryPiece(
            next=self.next,
            length=len(self)-offset,
            source=src,
            start=start+offset
        )

    @staticmethod
    def link(before: Piece, after: Piece):
        before.next = after
        after.prev = before

    def __repr__(self):
        return f"Piece(id={self.id}, prev={None if self.prev is None else self.prev.id}, next={None if self.next is None else self.next.id}, data[{len(self)}]={snippet(self.data)})"


@dataclass(repr=False)
class PrimaryPiece(Piece):
    """
    A primary piece holds string data.
    Only the two sentinel pieces at the start and end
    have no data.
    """
    _data: str = ''

    def __init__(self, *, prev: Piece|None=None, next: Piece|None=None, data: str='', allow_empty: bool=False):
        super().__init__(prev=prev, next=next)
        assert allow_empty or data
        self.extend(data)

    @property
    def data(self) -> str:
        return self._data

    def trim(self, n: int) -> Self:
        self._data = self._data[n:] if n>0 else self._data[:n]
        self._len -= abs(n)
        return self

    def extend(self, s: str):
        self._data += s
        self._len += len(s)

    def _ref(self) -> tuple[PrimaryPiece, int]:
        return self, 0


@dataclass(repr=False)
class SecondaryPiece(Piece):
    """
    A secondary piece represents a subset of a (single) primary piece,
    pointing to a slice of its data, i.e. source[start:][:length]
    """
    def __init__(self, *, source: PrimaryPiece, length: int, start: int=0, prev: Piece|None=None, next: Piece|None=None):
        super().__init__(prev=prev, next=next)
        self._src = source
        self._start = start
        self._len = length
        assert self._len > 0 and self._start + self._len <= len(self._src)

    def _ref(self) -> tuple[PrimaryPiece, int]:
        return self._src, self._start

    @property
    def data(self) -> str:
        return self._src.data[self._start:][:self._len]

    def trim(self, n: int) -> Self:
        self._start += max(0,n)
        self._len -= abs(n)
        assert self._len > 0 and self._start + self._len <= len(self._src)
        return self