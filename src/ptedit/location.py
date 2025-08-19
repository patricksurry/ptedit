from dataclasses import dataclass
from typing import Self, Literal

from .piece import Piece


@dataclass
class Location:
    piece: Piece
    offset: int = 0

    def __post_init__(self):
        assert 0 <= self.offset, \
            f"Loc can't have negative offset {self.offset}!"
        assert self.piece.length == 0 or self.offset < self.piece.length, \
            f"Loc offset {self.offset} >= length {self.piece.length}"

    def tuple(self) -> tuple[Piece, int]:
        return self.piece, self.offset

    def position(self) -> int:
        """Find the offset relative to the start of the piece chain"""
        p, offset = self.tuple()
        while True:
            p = p.prev
            if not p:
                break
            offset += p.length
        return offset

    def chain_length(self) -> Self:
        n = 0
        p = self.piece
        while p:
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
            while p.length <= offset and p.next:
                offset -= p.length
                p = p.next
            # did we fall off the end?
            if not p.next:
                offset = 0
        else:
            while offset < 0 and p.prev:
                p = p.prev
                offset += p.length
            # did we hit the start?
            if not p.prev:
                offset = 0
                p = p.next

        return Location(p, offset)

    @staticmethod
    def span_length(start: Self, end: Self) -> int:
        p = start.piece
        n = end.offset - start.offset
        while p != end.piece:
            n += p.length
            p = p.next
        return n

    @staticmethod
    def span_contains(loc: Self, start: Self, end: Self) -> bool:
        """
        Test whether loc is in the interval [start, end)
        """
        if loc.piece == start.piece and loc.offset < start.offset:
            return False

        if loc.piece == end.piece and loc.offset >= end.offset:
            return False

        p = start.piece
        while p.next:
            if p == loc.piece:
                return True
            if p == end.piece:
                break
            p = p.next

        return False

    @staticmethod
    def span_data(start: Self, end: Self) -> str:
        p, offset = start.tuple()
        q, q_offset = end.tuple()
        s = ''
        while p != q:
            s += p.data[offset:]
            offset = 0
            p = p.next
        s += p.data[offset:q_offset]
        return s
