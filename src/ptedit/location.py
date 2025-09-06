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

    def is_start(self) -> bool:
        assert self.piece.prev is not None
        return self.offset == 0 and self.piece.prev.prev is None

    def is_end(self) -> bool:
        return self.piece.next is None

    def chain_length(self) -> int:
        """Return number of pieces before start (status only)"""
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
            while offset < 0 and p.prev is not None and len(p.prev) != 0:
                p = p.prev
                offset += len(p)
            # did we hit the start?
            if offset < 0:
                offset = 0

        assert p is not None        # for the type checker
        return self.__class__(p, offset)

    """
    Since pieces *mostly* form a doubly linked list, and always do so
    in the active document, it's tempting to define comparison operators.
    However we often have side chains due to Edits which point
    back into the main document chain, meaning that
    before and after relationships are not necessarily symmetric.
    For example after editing the chain A <-> B <-> C
    we might end up with A <-> D <-> E <-> C and a side chain A <- B -> C
    Here B is after A but A is *not* before B, and vice versa for C.
    And D and B are neither before or after each other.
    So instead we define before and after separately.
    """

    def distance_before(self, other: Self) -> int | None:
        """if self is at or before other, returns positive distance, else None"""
        p = self.piece
        n = other.offset - self.offset
        while p is not None and p != other.piece:
            n += len(p)
            p = p.next
        return n if p is not None and n >= 0 else None

    def is_at_or_before(self, other: Self) -> bool:
        """return true if our next links lead to other"""
        return self.distance_before(other) is not None

    def is_strictly_before(self, other: Self) -> bool:
        d = self.distance_before(other)
        return d is not None and d > 0

    def distance_after(self, other: Self) -> int | None:
        """if self is at or after other, return positive distance, else None"""
        p = self.piece
        n = self.offset - other.offset
        while p != other.piece:
            p = p.prev
            if p is None:
                break
            n += len(p)
        return n if p is not None and n >= 0 else None

    def is_at_or_after(self, other: Self) -> bool:
        """return true if our prev links lead to other"""
        return self.distance_after(other) is not None

    def within(self, start: Self, end: Self) -> bool:
        """return true if self in [start, end)"""
        return self.is_at_or_after(start) and self.is_strictly_before(end)