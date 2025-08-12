
from __future__ import annotations
from dataclasses import dataclass

from .piece import Piece, PrimaryPiece
from .edit import Edit, EditStack


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


class PieceTable:
    def __init__(self, s: str=''):
        # Create sentinel pieces at the ends of the chain
        # These are the only Pieces that are empty
        self._start = PrimaryPiece(allow_empty=True)
        self._end = PrimaryPiece(allow_empty=True)
        Piece.link(self._start, self._end)

        # Set up our edit stack
        self.edit_stack = EditStack()

        self.set_point(self.get_start())
        if s:
            self.insert(s)
            self.set_point(self.get_start())

    def get_start(self) -> Location:
        return Location(self._start.next)

    def get_end(self) -> Location:
        return Location(self._end)

    @property
    def length(self) -> int:
        """count the number of characters in the document"""
        return self.location_to_offset(self.get_end())

    @property
    def data(self) -> str:
        return self.slice(self.get_start(), self.get_end())

    def offset_to_location(self, offset: int) -> Location:
        """
        Find the location for a global offset measured.
        If offset is positive we count forward from the start,
        if negative we count backward from the end
        """
        loc = self.get_start() if offset >= 0 else self.get_end()
        # Turn it into a relative move from the start or end
        return self.move_location(loc, offset)

    def location_to_offset(self, loc: Location) -> int:
        """Find the offset from the start of buffer to location"""
        p, offset = loc.tuple()
        while True:
            p = p.prev
            if not p:
                break
            offset += p.length
        return offset

    def move_location(self, loc: Location, delta: int) -> Location:
        """Move the location by delta (forward if positive else backward)"""
        if delta == 0:
            return loc

        offset = loc.offset + delta
        p = loc.piece

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

    def within_range(self, loc: Location, start: Location, end: Location) -> bool:
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

    def get_point(self) -> Location:
        return self._point

    def set_point(self, loc: Location) -> PieceTable:
        self._point = loc
        return self

    def move_point(self, delta: int) -> PieceTable:
        self._point = self.move_location(self._point, delta)
        return self

    def insert(self, s: str) -> PieceTable:
        if not s:
            return self

        p, offset = self.get_point().tuple()
        # inserting between two existing pieces?
        if not offset:
            # continuing a previous insert?
            edit = self.edit_stack.peek()
            if edit and edit.ins == p.prev:
                ins = p.prev
                ins.length += len(s)
                ins.data += s
                edit = None
            else:
                # insert new piece between p.prev and p
                before, after = p.prev, p
                ins = PrimaryPiece(length=len(s), data=s)
                edit = Edit(before, after, ins=ins)
        else:
            # split piece so we can insert
            before, after = p.prev, p.next
            pre, post = p.split(offset)
            ins = PrimaryPiece(length=len(s), data=s)
            edit = Edit(before, after, pre=pre, ins=ins, post=post)

        self.edit_stack.push(edit)

        # in all cases advance point after the insertion point
        self.set_point(Location(ins.next))
        return self

    def delete(self, length: int) -> PieceTable:
        # +length deletes to the right, -length deletes to the left
        if not length:
            return self

        pt = self.get_point()
        loc = self.move_location(pt, length)

        if length < 0:
            # for convenience, ensure point is before loc
            loc, pt = pt, loc
            length = -length

        # are we deleting between two pieces?
        before = pt.piece.prev
        if not pt.offset:
            pre = None
        else:
            pre = pt.piece.split(pt.offset)[0]

        if not loc.offset:
            after = loc.piece
            post = None
        else:
            after = loc.piece.next
            post = loc.piece.split(loc.offset)[1]

        self.edit_stack.push(Edit(before, after, pre=pre, post=post))
        self.set_point(Location(post or after))
        return self

    def replace(self, s: str) -> PieceTable:
        if not s:
            return self

        p, offset = self.get_point().tuple()

        # can we continue a previous replace?
        if offset == 0:
            edit = self.edit_stack.peek()
            if edit and edit.ins == p.prev and edit.post == p and len(s) < p.length:
                inplace = True
                edit.ins.data += s
                edit.ins.length += len(s)
                edit.post.start += len(s)
                edit.post.length -= len(s)
                self.edit_stack.push(None)
                self.set_point(Location(edit.post))
                return self

        # delete
        self.delete(len(s))
        edit = self.edit_stack.peek()
        # a new edit won't have an ins but just in case...
        if edit.ins:
            self.insert(s)
            return self

        # undo the delete so we can relink with inserted text
        self.edit_stack.undo()
        ins = PrimaryPiece(length=len(s), data=s)
        self.edit_stack.push(Edit(edit.before, edit.after, edit.pre, ins, edit.post))
        self.set_point(Location(edit.post or edit.after))
        return self

    def undo(self) -> PieceTable:
        self.edit_stack.undo()
        return self

    def redo(self) -> PieceTable:
        self.edit_stack.redo()
        return self

    def slice(self, start: Location, end: Location) -> str:
        p, offset = start.tuple()
        q, q_offset = end.tuple()
        s = ''
        while p != q:
            s += p.data[offset:]
            offset = 0
            p = p.next
        s += p.data[offset:q_offset]
        return s

    def get_char(self) -> str:
        """Return character after point"""
        p, offset = self.get_point().tuple()
        return p.data[offset:][:1]

    def next_char(self) -> str:
        """Return character after point and advance point"""
        c = self.get_char()
        self.move_point(1)
        return c

    def prev_char(self) -> str:
        """Return character preceding point and retreat point"""
        self.move_point(-1)
        return self.get_char()

    def get_string(self, n = 1) -> str:
        """Return up to n characters from point through end of buffer"""
        pt = self.get_point()
        s = ''
        while n:
            s += self.next_char()
            n -= 1
        self.pt = pt
        return s

    def find_char_forward(self, chars: str) -> PieceTable:
        # move point before the first occurrence of a char in chars
        while self.get_point() != self.get_end():
            if self.next_char() in chars:
                self.move_point(-1)
                break
        return self

    def find_char_backward(self, chars: str) -> PieceTable:
        # move point before the first occurrence of a char in chars
        while self.get_point() != self.get_start():
            if self.prev_char() in chars:
                break
        return self

    def __str__(self):
        spans = []
        p = self._start
        while True:
            spans.append(p.data)
            if p.next is None:
                break
            p = p.next
        return '|' + '|'.join(spans) + '|'

    def __repr__(self):
        lines = []
        p = self._start
        while True:
            lines.append(repr(p))
            if p.next is None:
                break
            p = p.next
        return '\n'.join(lines)