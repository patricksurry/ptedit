
from __future__ import annotations
from typing import Callable, ParamSpec, TypeVar, Concatenate
from enum import Enum

from .piece import Piece, PrimaryPiece
from .location import Location
from .edit import Edit


whitespace = ' \t\n'


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
        self.dirty = False
        self._n_get_char_calls = 0  # for performance testing
        self._reset(s)

    def _reset(self, s: str):
        Piece.link(self._start, self._end)
        p = PrimaryPiece(data=s) if s else None
        self._edit = Edit(self._start, self._end, ins=p)
        self.set_point_start()

    def watch(self, watcher: Watcher):
        self._watchers.append(watcher)

    def notify_watchers(self):
        self.dirty = True
        start, end = (self._edit.get_change_start(), self._edit.get_change_end())
        for watcher in self._watchers:
            watcher(start, end)

    @mutator
    def squash(self):
        self._reset(self.get_data())

    def at_start(self) -> bool:
        return self._point.is_start()

    def at_end(self) -> bool:
        return self._point.is_end()

    def __len__(self) -> int:
        """count the number of characters in the document"""
        return len(self.get_data())

    def piece_counts(self) -> tuple[int, int]:
        """Count pieces to point and in full doc for extended status"""
        return self._point.chain_length(), Location(self._end).chain_length()

    def edit_counts(self) -> tuple[int, int]:
        """Count active edits and total (including undone) edits for extended status"""
        edit = self._edit
        while edit.next:
            edit = edit.next
        return self._edit.chain_length(), edit.chain_length()

    def get_point(self) -> Location:
        return self._point

    def set_point(self, loc: Location) -> Document:
        self._point = loc
        return self

    def set_point_start(self) -> Document:
        assert self._start.next is not None
        self._point = Location(self._start.next)
        return self

    def set_point_end(self) -> Document:
        self._point = Location(self._end)
        return self

    def move_point(self, delta: int) -> Document:
        self._point = self._point.move(delta)
        return self

    def get_data(self, start: Location|None=None, end: Location|None=None) -> str:
        assert self._start.next is not None
        p, offset = start.tuple() if start else (self._start.next, 0)
        q, q_offset = end.tuple() if end else (self._end, 0)

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
        return self._point.piece.data[offset:offset+1] or '\0'

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
        while not match and not pt.is_end():
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
        while not match and not pt.is_start():
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
        self._edit = self._edit.merge_or_append(self.get_point(), insert=s)
        self.set_point(self._edit.get_change_end())
        return self

    @mutator
    def delete(self, n: int) -> Document:
        """
        Delete characters from point
        +n deletes to the right, -n deletes to the left
        """
        if not n:
            return self

        self._edit = self._edit.merge_or_append(self.get_point(), delete=n)
        self.set_point(self._edit.get_change_end())
        return self

    @mutator
    def replace(self, s: str) -> Document:
        """Replace len(s) characters right of the point"""
        if not s:
            return self

        self._edit = self._edit.merge_or_append(self.get_point(), delete=len(s), insert=s)
        self.set_point(self._edit.get_change_end())
        return self

    @property
    def has_undo(self) -> bool:
        # for testing
        return self._edit.prev is not None

    @mutator
    def undo(self) -> Document:
        if self._edit.prev:
            self.set_point(self._edit.undo())
            self._edit = self._edit.prev
        return self

    @mutator
    def redo(self) -> Document:
        if self._edit.next:
            self._edit = self._edit.next
            self.set_point(self._edit.redo())
        return self

    def __str__(self):
        p = self._start.next
        s: str = ''
        while p:
            s += '|'
            if self._point.piece == p:
                s += p.data[:self._point.offset] + '^' + p.data[self._point.offset:]
            else:
                s += p.data
            p = p.next
        return s

    def __repr__(self):
        lines: list[str] = []
        p = self._start
        while True:
            lines.append(repr(p))
            if p.next is None:
                break
            p = p.next
        return '\n'.join(lines)