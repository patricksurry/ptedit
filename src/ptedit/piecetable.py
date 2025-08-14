
from __future__ import annotations

from .piece import Piece, PrimaryPiece
from .location import Location
from .editstack import Edit, EditStack


class PieceTable:
    def __init__(self, s: str=''):
        # Create sentinel pieces at the ends of the chain
        # These are the only Pieces that are empty
        self._start = PrimaryPiece(allow_empty=True)
        self._end = PrimaryPiece(allow_empty=True)
        if s:
            # any initial data should be immutable
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

    def find_char_forward(self, chars: str) -> PieceTable:
        # move point before the first occurrence of a char in chars
        # so need move_point(1) to do repeated searches
        while self.get_point() != self.get_end():
            if self.next_char() in chars:
                self.move_point(-1)
                break
        return self

    def find_char_backward(self, chars: str) -> PieceTable:
        # move point *after* the first occurrence of a char in chars
        # so need move_point(-1) to do repeated searches
        # see 9.13.4.1 Moving by Words

        while self.get_point() != self.get_start():
            if self.prev_char() in chars:
                self.move_point(1)
                break
        return self

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