
from __future__ import annotations

from .piece import Piece, PrimaryPiece
from .location import Location
from .editstack import Edit, EditStack


class PieceTable:
    def __init__(self, s: str=''):
        """
        Create sentinel pieces at the ends of the chain
        These are the only Pieces that are empty
        """
        self._start = PrimaryPiece(allow_empty=True)
        self._end = PrimaryPiece(allow_empty=True)
        if s:
            # any initial data is immutable, so don't represent as an Edit
            p = PrimaryPiece(s)
            Piece.link(self._start, p)
            Piece.link(p, self._end)
        else:
            Piece.link(self._start, self._end)

        self.set_point(self.get_start())

        # Set up our edit stack
        self.edit_stack = EditStack()

    def get_start(self) -> Location:
        return Location(self._start.next)

    def get_end(self) -> Location:
        return Location(self._end)

    @property
    def length(self) -> int:
        """count the number of characters in the document"""
        return Location.span_length(self.get_start(), self.get_end())

    def get_point(self) -> Location:
        return self._point

    def set_point(self, loc: Location) -> PieceTable:
        self._point = loc
        return self

    def move_point(self, delta: int) -> PieceTable:
        self._point = self._point.move(delta)
        return self

    @property
    def data(self) -> str:
        return Location.span_data(self.get_start(), self.get_end())

    def get_char(self) -> str:
        """Return character after point, without moving point"""
        offset = self._point.offset
        return self._point.piece.data[offset:offset+1]

    def next_char(self) -> str:
        """Return character after point and advance point"""
        c = self.get_char()
        self.move_point(1)
        return c

    def prev_char(self) -> str:
        """Return character preceding point and retreat point"""
        self.move_point(-1)
        return self.get_char()

    def find_char_forward(self, chars: str) -> bool:
        """
        move point before the first occurrence of a char in chars
        so need move_point(1) to do repeated searches
        """
        match = False
        while not match and self.get_point() != self.get_end():
            match = self.next_char() in chars
        if match:
            self.move_point(-1)
        return match

    def find_not_char_forward(self, chars: str) -> bool:
        """
        move point before the first occurrence of a char in chars
        so need move_point(1) to do repeated searches
        """
        match = False
        while not match and self.get_point() != self.get_end():
            match = self.next_char() not in chars
        if match:
            self.move_point(-1)
        return match

    def find_char_backward(self, chars: str) -> PieceTable:
        """
        move point *after* the first occurrence of a char in chars
        so need move_point(-1) to do repeated searches
        see 9.13.4.1 Moving by Words
        """
        match = False
        while not match and self.get_point() != self.get_start():
            match = self.prev_char() in chars
        if match:
            self.move_point(1)
        return match

    def find_not_char_backward(self, chars: str) -> PieceTable:
        """
        move point *after* the first occurrence of a char in chars
        so need move_point(-1) to do repeated searches
        see 9.13.4.1 Moving by Words
        """
        match = False
        while match and self.get_point() != self.get_start():
            match = self.prev_char() not in chars
        if match:
            self.move_point(1)
        return match

    def find_forward(self, s: str) -> bool:
        """
        Find a string at or after the point, leaving the point
        *after* the match, or at end if no match
        """
        assert len(s) != 0, "find_forward: expected non-empty string"

        pt = self.get_point()
        match = False
        while not match and pt != self.get_end():
            self.set_point(pt)
            pt = pt.move(1)
            for c in s:
                match = self.next_char() == c
                if not match:
                    break
        return match

    def find_backward(self, s: str) -> bool:
        """
        Find a string that ends before the point, leaving the point
        *after* the match, or at start if no match.
        """
        assert len(s) != 0, "find_backward: expected non-empty string"

        match = self.get_point().position() <= len(s)
        self.move_point(-len(s))
        pt = self.get_point()
        while not match and pt != self.get_start():
            pt = pt.move(-1)
            self.set_point(pt)
            for c in s:
                match = self.next_char() == c
                if not match:
                    break
        return match

    def insert(self, s: str) -> PieceTable:
        if not s:
            return self

        p, offset = self.get_point().tuple()
        inplace = False
        # inserting between two existing pieces?
        if not offset:
            # continuing a previous insert?
            edit = self.edit_stack.peek()
            if edit and edit.ins == p.prev:
                ins = p.prev
                ins.length += len(s)
                ins.data += s
                inplace = True
            else:
                # insert new piece between p.prev and p
                before, after = p.prev, p
                ins = PrimaryPiece(data=s)
                edit = Edit(before, after, ins=ins)
        else:
            # split piece so we can insert
            before, after = p.prev, p.next
            pre, post = p.split(offset)
            ins = PrimaryPiece(data=s)
            edit = Edit(before, after, pre=pre, ins=ins, post=post)

        self.edit_stack.push(None if inplace else edit)
        self.set_point(edit.location())
        return self

    def delete(self, length: int) -> PieceTable:
        # +length deletes to the right, -length deletes to the left
        if not length:
            return self

        pt = self.get_point()
        loc = pt.move(length)

        if length < 0:
            # for convenience, ensure point is before loc
            loc, pt = pt, loc
            length = -length

        # are we deleting between two pieces?
        before = pt.piece.prev
        if pt.offset == 0:
            # Can we continue a previous deletion?
            edit = self.edit_stack.peek()
            if (
                edit and not edit.ins
                and edit.pre == before and edit.post == pt.piece
                and edit.post.length > length
            ):
                edit.post.start += length
                edit.post.length -= length
                self.edit_stack.push(None)
                self.set_point(edit.location())
                return None

            pre = None
        else:
            pre = pt.piece.split(pt.offset)[0]

        if loc.offset == 0:
            # Can we continue a previous deletion?
            after = loc.piece
            post = None

            edit = self.edit_stack.peek()
            if (
                edit and not edit.ins
                and edit.pre == pt.piece and edit.post == after
                and edit.pre.length > length
            ):
                edit.pre.length -= length
                self.edit_stack.push(None)
                self.set_point(edit.location())
                return None

        else:
            after = loc.piece.next
            post = loc.piece.split(loc.offset)[1]

        edit = Edit(before, after, pre=pre, post=post)
        self.edit_stack.push(edit)
        self.set_point(edit.location())
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
                self.set_point(edit.location())
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
        ins = PrimaryPiece(data=s)
        edit = Edit(edit.before, edit.after, edit.pre, ins, edit.post)
        self.edit_stack.push(edit)
        self.set_point(edit.location())
        return self

    def undo(self) -> PieceTable:
        if loc := self.edit_stack.undo():
            self.set_point(loc)
        return self

    def redo(self) -> PieceTable:
        if loc := self.edit_stack.redo():
            self.set_point(loc)
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