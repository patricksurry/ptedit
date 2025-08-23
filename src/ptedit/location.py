from dataclasses import dataclass
from typing import Self

from .piece import Piece


@dataclass
class Location:
    piece: Piece
    offset: int = 0

    def __post_init__(self):
        assert 0 <= self.offset, \
            f"Loc can't have negative offset {self.offset}!"
        assert len(self.piece) == 0 or self.offset < len(self.piece), \
            f"Loc offset {self.offset} >= length {len(self.piece)}"

    def tuple(self) -> tuple[Piece, int]:
        return self.piece, self.offset

    def position(self) -> int:
        """Find the offset relative to the start of the piece chain"""
        p, offset = self.tuple()
        while True:
            p = p.prev
            if p is None:
                break
            offset += len(p)
        return offset

    def chain_length(self) -> int:
        n = 0
        p = self.piece
        while p is not None:
            p = p.prev
            n += 1
        return n

    def move(self, delta: int) -> Self:
        """Move the location by delta (forward if positive else backward)"""
        if delta == 0:
            return self

        offset = self.offset + delta
        p = self.piece
        if offset > 0:
            while len(p) <= offset and p.next is not None:
                offset -= len(p)
                p = p.next
            # did we fall off the end?
            if p.next is None:
                offset = 0
        else:
            while offset < 0 and p.prev is not None:
                p = p.prev
                offset += len(p)
            # did we hit the start?
            if p.prev is None:
                offset = 0
                p = p.next

        assert p is not None        # for the type checker
        return self.__class__(p, offset)

    def _half_sub(self, b: Self) -> int | None:
        # return | self - b | if self >=b else None
        p = b.piece
        n = self.offset - b.offset
        while p is not None and p != self.piece:
            n += len(p)
            p = p.next
        return n if p is not None else None

    def __sub__(self, b: Self) -> int | None:
        v = self._half_sub(b)
        if v is None:
            v = b._half_sub(self)
            if v is not None:
                v = -v
        return v

    def __lt__(self, b: Self):
        p = self.piece
        if p == b.piece:
            return self.offset < b.offset

        # scan upwards for b
        while p is not None and p != b.piece:
            p = p.next
        return p is not None

    def __le__(self, b: Self):
        return self == b or self < b

    def __gt__(self, b: Self):
        return b < self

    def __ge__(self, b: Self):
        return b <= self



