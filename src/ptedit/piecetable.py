
from __future__ import annotations
from typing import Callable, ParamSpec, TypeVar, Concatenate
from enum import Enum

from .piece import Piece, PrimaryPiece
from .location import Location
from .editstack import Edit, EditStack


class MatchMode(Enum):
    EXACT_CASE = 0          # exact match
    IGNORE_CASE = 1         # ignore letter case
    SMART_CASE = 2          # lower case matches either, upper matches upper


def is_char_match(pattern: str, c: str, mode: MatchMode = MatchMode.EXACT_CASE) -> bool:
    """
    Compare two characters for equality, with optional case insensitivity.
    """
    if mode == MatchMode.EXACT_CASE:
        return pattern == c
    elif mode == MatchMode.IGNORE_CASE:
        return pattern.lower() == c.lower()
    elif mode == MatchMode.SMART_CASE:
        return pattern == (c.lower() if pattern.islower() else c)
    else:
        raise ValueError(f"Unknown match mode: {mode}")


P = ParamSpec('P')  # Represents the parameters of the decorated function
R = TypeVar('R')    # Represents the return type of the decorated function


def mutator(method: Callable[Concatenate[Document, P], R]) -> Callable[Concatenate[Document, P], R]:
    def wrapped(self: Document, *args: P.args, **kwargs: P.kwargs) -> R:
        retval = method(self, *args, **kwargs)
        self.notify_watchers()
        return retval
    return wrapped


Watcher = Callable[[Location,Location],None]


class Document:
    def __init__(self, s: str=''):
        self._watchers: list[Watcher] = []

        # Create sentinel pieces at the ends of the chain
        # These are the only Pieces that are empty
        self._start: Piece = PrimaryPiece(allow_empty=True)
        self._end: Piece = PrimaryPiece(allow_empty=True)
        self._reset(s)
        self.dirty = False
        self._n_get_char_calls = 0  # for performance testing

    def _reset(self, s: str):
        if s:
            # any initial data is immutable, so don't represent as an Edit
            p = PrimaryPiece(data=s)
            Piece.link(self._start, p)
            Piece.link(p, self._end)
        else:
            Piece.link(self._start, self._end)

        self.set_point(self.get_start())

        # Set up our edit stack
        self.edit_stack = EditStack()

    def watch(self, watcher: Watcher):
        self._watchers.append(watcher)

    def notify_watchers(self):
        self.dirty = True
        edit = self.edit_stack.peek()
        if edit:
            start, end = (edit.get_start(), edit.get_end())
        else:
            start, end = (self.get_start(), self.get_end())
        for watcher in self._watchers:
            watcher(start, end)

    @mutator
    def squash(self):
        self._reset(self.get_data())

    def get_start(self) -> Location:
        assert self._start.next is not None
        return Location(self._start.next)

    def get_end(self) -> Location:
        return Location(self._end)

    def at_start(self) -> bool:
        return self._point.piece == self._start.next and self._point.offset == 0

    def at_end(self) -> bool:
        return self._point.piece == self._end

    def __len__(self) -> int:
        """count the number of characters in the document"""
        return len(self.get_data())

    def get_point(self) -> Location:
        return self._point

    def set_point(self, loc: Location) -> Document:
        self._point = loc
        return self

    def move_point(self, delta: int) -> Document:
        self._point = self._point.move(delta)
        return self

    def get_data(self, start: Location|None=None, end: Location|None=None) -> str:
        p, offset = (start or self.get_start()).tuple()
        q, q_offset = (end or self.get_end()).tuple()

        s = ''
        while p != q and p.next is not None:
            s += p.data[offset:]
            offset = 0
            p = p.next
        s += p.data[offset:q_offset]
        return s

    def get_char(self) -> str:
        """Return character after point, without moving point"""
        self._n_get_char_calls += 1
        offset = self._point.offset
        return self._point.piece.data[offset:offset+1]

    @property
    def n_get_char_calls(self) -> int:
        return self._n_get_char_calls

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
        while not match and not self.at_end():
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
        while not match and not self.at_end():
            match = self.next_char() not in chars
        if match:
            self.move_point(-1)
        return match

    def find_char_backward(self, chars: str) -> bool:
        """
        move point *after* the first occurrence of a char in chars
        so need move_point(-1) to do repeated searches
        see 9.13.4.1 Moving by Words
        """
        match = False
        while not match and not self.at_start():
            match = self.prev_char() in chars
        if match:
            self.move_point(1)
        return match

    def find_not_char_backward(self, chars: str) -> bool:
        """
        move point *after* the first occurrence of a char in chars
        so need move_point(-1) to do repeated searches
        see 9.13.4.1 Moving by Words
        """
        match = False
        while match and not self.at_start():
            match = self.prev_char() not in chars
        if match:
            self.move_point(1)
        return match

    def find_forward(self, pattern: str, mode: MatchMode) -> bool:
        """
        Find a string at or after the point, leaving the point
        *after* the match, or at end if no match
        """
        assert len(pattern) != 0, "find_forward: expected non-empty string"

        pt = self.get_point()
        match = False
        while not match and pt != self.get_end():
            self.set_point(pt)
            pt = pt.move(1)
            for c in pattern:
                match = is_char_match(c, self.next_char(), mode)
                if not match:
                    break
        return match

    def find_backward(self, pattern: str, mode: MatchMode) -> bool:
        """
        Find a string that ends before the point, leaving the point
        *after* the match, or at start if no match.
        """
        assert len(pattern) != 0, "find_backward: expected non-empty string"

        match = self.get_point().position() <= len(pattern)
        self.move_point(-len(pattern))
        pt = self.get_point()
        while not match and pt != self.get_start():
            pt = pt.move(-1)
            self.set_point(pt)
            for c in pattern:
                match = is_char_match(c, self.next_char(), mode)
                if not match:
                    break
        return match

    @mutator
    def insert(self, s: str) -> Document:
        if not s:
            return self

        p, offset = self.get_point().tuple()
        inplace = False
        # inserting between two existing pieces?
        if offset == 0:
            # continuing a previous insert?
            edit = self.edit_stack.peek()
            if edit is not None and edit.ins is not None and p.prev == edit.ins:
                edit.ins.extend(s)
                inplace = True
            else:
                # insert new piece between p.prev and p
                before, after = p.prev, p
                assert before is not None
                ins = PrimaryPiece(data=s)
                edit = Edit(before, after, ins=ins)
        else:
            # split piece so we can insert
            before, after = p.prev, p.next
            assert before is not None and after is not None
            pre, post = p.split(offset)
            ins = PrimaryPiece(data=s)
            edit = Edit(before, after, pre=pre, ins=ins, post=post)

        self.edit_stack.push(None if inplace else edit)
        self.set_point(edit.get_end())
        return self

    @mutator
    def delete(self, n: int) -> Document:
        # +n deletes to the right, -n deletes to the left
        if not n:
            return self

        pt = self.get_point()
        loc = pt.move(n)

        if n < 0:
            # for convenience, ensure point is before loc
            loc, pt = pt, loc
            n = -n

        # are we deleting between two pieces?
        before = pt.piece.prev
        if pt.offset == 0:
            # Can we continue a previous deletion?
            edit = self.edit_stack.peek()
            if (
                edit and edit.ins is None
                and edit.pre == before and edit.post == pt.piece
                and edit.post is not None and len(edit.post) > n
            ):
                edit.post.trim(n, 0)
                self.edit_stack.push(None)
                self.set_point(edit.get_end())
                return self

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
                and edit.pre is not None and len(edit.pre) > n
            ):
                edit.pre.trim(0, n)
                self.edit_stack.push(None)
                self.set_point(edit.get_end())
                return self

        else:
            after = loc.piece.next
            post = loc.piece.split(loc.offset)[1]

        assert before is not None and after is not None
        edit = Edit(before, after, pre=pre, post=post)
        self.edit_stack.push(edit)
        self.set_point(edit.get_end())
        return self

    @mutator
    def replace(self, s: str) -> Document:
        if not s:
            return self

        p, offset = self.get_point().tuple()

        # can we continue a previous replace?
        if offset == 0:
            edit = self.edit_stack.peek()
            if (
                    edit is not None
                    and edit.ins is not None and edit.ins == p.prev
                    and edit.post is not None and edit.post == p
                    and len(s) < len(p)
            ):
                edit.ins.extend(s)
                edit.post.trim(len(s), 0)
                self.edit_stack.push(None)
                self.set_point(edit.get_end())
                return self

        # delete
        self.delete(len(s))
        edit = self.edit_stack.peek()
        assert edit is not None     # we just did a delete
        # a new edit won't have an ins but just in case...
        if edit.ins is not None:
            self.insert(s)
            return self

        # undo the delete so we can relink with inserted text
        self.edit_stack.undo()
        ins = PrimaryPiece(data=s)
        edit = Edit(edit.before, edit.after, edit.pre, ins, edit.post)
        self.edit_stack.push(edit)
        self.set_point(edit.get_end())
        return self

    @mutator
    def undo(self) -> Document:
        if loc := self.edit_stack.undo():
            self.set_point(loc)
        return self

    @mutator
    def redo(self) -> Document:
        if loc := self.edit_stack.redo():
            self.set_point(loc)
        return self

    def __str__(self):
        spans: list[str] = []
        p = self._start
        while True:
            spans.append(p.data)
            if p.next is None:
                break
            p = p.next
        return '|' + '|'.join(spans) + '|'

    def __repr__(self):
        lines: list[str] = []
        p = self._start
        while True:
            lines.append(repr(p))
            if p.next is None:
                break
            p = p.next
        return '\n'.join(lines)