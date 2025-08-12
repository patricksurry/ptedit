from __future__ import annotations
from typing import ClassVar
from dataclasses import dataclass


def snippet(s, n=8):
    return f"'{s}'" if len(s) <= n else f"'{s[:n-2]}...'"


@dataclass(kw_only=True)
class Piece:
    """A generic piece of text"""
    _id: ClassVar[int] = 0
    prev: Piece | None = None
    next: Piece | None = None
    length: int = 0

    id: int = 0

    @property
    def lines(self):
        return self.data.count('\n')

    @property
    def data(self):
        ...

    def _data_ref(self) -> tuple[PrimaryPiece, int]:
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
        assert 0 < offset < self.length
        src, start = self._data_ref()
        return (
            SecondaryPiece(
                prev=self.prev,
                length=offset,
                source=src,
                start=start,
            ),
            SecondaryPiece(
                next=self.next,
                length=self.length-offset,
                source=src,
                start=start+offset
            )
        )

    @staticmethod
    def link(before: Piece, after: Piece):
        before.next = after
        after.prev = before

    def __repr__(self):
        return f"Piece(id={self.id}, prev={self.prev and self.prev.id}, next={self.next and self.next.id}, data[{self.length}]={snippet(self.data)})"


@dataclass(repr=False)
class PrimaryPiece(Piece):
    """
    A primary piece holds string data.
    Only the two sentinel pieces at the start and end
    have empty data.
    """
    data: str = ''
    allow_empty: bool = False

    def __post_init__(self):
        super().__post_init__()
        assert self.allow_empty or self.data

    def _data_ref(self) -> tuple[PrimaryPiece, int]:
        return self, 0


@dataclass(repr=False)
class SecondaryPiece(Piece):
    """A secondary piece points to data held in a primary piece"""
    source: PrimaryPiece
    start: int = 0

    def _data_ref(self) -> tuple[PrimaryPiece, int]:
        return self.source, self.start

    @property
    def data(self):
        return self.source.data[self.start:][:self.length]
