from __future__ import annotations
from typing import cast, Self
from dataclasses import dataclass

from .piece import Piece, PrimaryPiece, SecondaryPiece
from .location import Location


@dataclass
class Edit:
    r"""
    An edit tracks how the piece chain changes, with before/after
    bracketing the change.  To do (or undo) the edit,
    we swap the before.next and after.prev links from the old to new fragment
    (or vice versa)
                         +--\                  \----+
                     +-->|   \ ... original ... \   | --+
        +--------+   |   +----\                  \--+   |   +-------+
        | before | --+                                  +-->| after |
        +--------+   |   +-----+   +-----+   +------+   |   +-------+
                     +-->| pre |-->| ins |-->| post | --+
                         +-----+   +-----+   +------+
    """
    # The Edit stores pointers to the unchanged pieces before/after,
    # as well as the original value of before.next and after.prev
    # (i.e. the head and tail of the original fragment)

    before: Piece
    after: Piece

    # The Edit contains 0-3 new pieces pre/ins/post describing the new fragment
    pre: SecondaryPiece | None = None
    ins: PrimaryPiece | None = None     # for an insertion when new data is created
    post: SecondaryPiece | None = None

    prev: Self | None = None
    next: Self | None = None

    def __post_init__(self):
        # preserve the original links for undo
        self._links = (self.before.next, self.after.prev)

        assert self.after is not None and self.before.next is not None
        d = Location(self.after).distance_after(Location(self.before.next))
        assert d is not None and d >= (
            (0 if self.pre is None else len(self.pre))
            + (0 if self.post is None else len(self.post))
        ), f"Edit excluding insert is no longer than before {d}"

        pieces: list[Piece] = [p for p in cast(list[Piece|None], [
            self.before,
            self.pre,
            self.ins,
            self.post,
            self.after,
        ]) if p is not None]
        assert pieces, "Edit: empty!"
        # link up the new pieces
        for pair in zip(pieces[:-1], pieces[1:]):
            Piece.link(*pair)
        self._applied = True

    def chain_length(self) -> int:
        """Return number of edits up to and including this one"""
        n = 0
        edit = self
        while edit is not None:
            edit = edit.prev
            n += 1
        return n

    def append(self, pt: Location, delete: int = 0, insert: str = '') -> Self:
        """Chain a new edit to this one and return it"""
        if delete == 0:
            pre, post = pt.piece.split(pt.offset) if pt.offset else (None, None)
            before, after = pt.piece.prev, pt.piece.next if pt.offset else pt.piece
        else:
            loc = pt.move(delete)
            left, right = (loc, pt) if delete < 0 else (pt, loc)
            pre = left.piece.split(left.offset)[0] if left.offset else None
            post = right.piece.split(right.offset)[1] if right.offset else None
            before, after = left.piece.prev, right.piece.next if right.offset else right.piece

        ins = PrimaryPiece(data=insert) if insert else None

        assert before is not None and after is not None
        edit = self.__class__(before=before, after=after, pre=pre, post=post, ins=ins, prev=self)
        self.next = edit
        return edit

    def _swap(self):
        links = self.before.next, self.after.prev
        self.before.next, self.after.prev = self._links
        self._links = links
        self._applied = not self._applied

    def get_start(self) -> Location:
        """
        The edit starts after pre, or the equivalent offset if undone
        """
        loc = Location(self.before)
        if self.pre is not None:
            loc = loc.move(len(self.pre))
        return loc

    def get_end(self) -> Location:
        """
        The end of the edit (where the point lands) is after ins and before post,
        or the equivalent offset prior to after when undone
        """
        loc = Location(self.after)
        if self.post is not None:
            # When applied this is just Location(self.post)
            # but after an undo, we need to move an equivalent length backward
            loc = loc.move(-len(self.post))
        return loc

    def merge_or_append(self, pt: Location, delete: int = 0, insert: str = '') -> Self:
        """
        Either update self or return a new Edit
        """
        if self.prev is None or pt != self.get_end():
            return self.append(pt, delete, insert)

        if delete:
            p = self.post if delete > 0 else (self.ins or self.pre)
            if not p or len(p) <= abs(delete):
                return self.append(pt, delete, insert)
            p.trim(delete)

        if insert:
            if self.ins:
                self.ins.extend(insert)
            else:
                self.ins = PrimaryPiece(data=insert)
                Piece.link(self.pre or self.before, self.ins)
                Piece.link(self.ins, self.post or self.after)

        return self

    def undo(self) -> Location:
        """Undo this edit"""
        assert self._applied, "undo: Edit already undone"
        self._swap()
        return self.get_end()

    def redo(self) -> Location:
        """Redo this edit"""
        assert not self._applied, "redo: Edit already applied"
        self._swap()
        return self.get_end()

