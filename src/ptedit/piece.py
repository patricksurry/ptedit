from __future__ import annotations
from typing import ClassVar
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

    id: int = 0             # for debugging it's useful to enumerate pieces

    @property
    def data(self) -> str:
        ...

    def __len__(self) -> int:
        return len(self.data)

    def _ref(self) -> tuple[PrimaryPiece, int]:
        ...

    def __post_init__(self):
        """Number pieces sequentially for debugging"""
        self.id = Piece._id
        Piece._id += 1

    def split(self, offset: int) -> tuple[SecondaryPiece, SecondaryPiece]:
        """
        Split a piece at an internal boundary, returning two new pieces
        Note the new pieces are linked back to their existing neighbors
        but are *not* linked *from* those neighbors.
        They are also not linked to each other.
        """
        assert 0 < offset < len(self)
        src, start = self._ref()
        return (
            SecondaryPiece(
                prev=self.prev,
                length=offset,
                source=src,
                start=start,
            ),
            SecondaryPiece(
                next=self.next,
                length=len(self)-offset,
                source=src,
                start=start+offset
            )
        )

    @staticmethod
    def link(before: Piece, after: Piece):
        before.next = after
        after.prev = before

    def __repr__(self):
        return f"Piece(id={self.id}, prev={self.prev and self.prev.id}, next={self.next and self.next.id}, data[{len(self)}]={snippet(self.data)})"


@dataclass(repr=False)
class PrimaryPiece(Piece):
    """
    A primary piece holds string data.
    Only the two sentinel pieces at the start and end
    have no data.
    """
    def __init__(self, *, prev: Piece|None=None, next: Piece|None=None, data: str='', allow_empty: bool=False):
        super().__init__(prev=prev, next=next)
        assert allow_empty or data
        self._data = data

    @property
    def data(self) -> str:
        return self._data

    def extend(self, s: str):
        self._data += s

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

    def trim(self, left: int=0, right: int=0):
        self._start += left
        self._len -= left + right
        assert self._len > 0 and self._start + self._len <= len(self._src)