from __future__ import annotations
from typing import cast, Self

from .piece import Piece, PrimaryPiece, SecondaryPiece
from .location import Location


class Edit:
    r"""
    An Edit tracks each change to the piece chain.
    The Edit owns up to three new pieces, pre/ins/post.
    An empty Edit occurs (for example) when we exactly delete an existing
    piece.  We also insert an empty Edit in a new (empty) document.

    We store a pointer to the unlinked first/last piece so that we can undo the edit.
    Even though the unlinked pieces are no longer in the doc piece chain,
    their back-links (first.prev and last.next) tell us where they belong.
    When the unlinked fragment is empty, for example when an Edit is inserted
    between two existing pieces, or after undoing an empty Edit,
    then unlinked first == before.next == after and last == after.prev == before.
    Because these pieces are still in the active chain, their backlinks may
    change but luckily they tell us after/before directly.

                       +------\                 \-------+
                  +--> | first \ .. unlinked ..  \ last | --+
    +--------+    |    +--------\                 \-----+   |    +-------+
    | before | ---+                                         +--> | after |
    +--------+    |    +------+     +------+     +------+   |    +-------+
                  +--> | pre  | --> | ins  | --> | post | --+
                       +------+     +------+     +------+

    """
    def __init__(self,
        before: Piece,
        after: Piece,

        # The Edit contains 0-3 new pieces pre/ins/post describing the new fragment
        pre: SecondaryPiece | None = None,
        ins: PrimaryPiece | None = None,     # for an insertion when new data is created
        post: SecondaryPiece | None = None,

        # Edits form a linked list supporting undo/redo
        prev: Self | None = None,
        next: Self | None = None,
    ):
        self.pre = pre
        self.post = post
        self.ins = ins
        self.prev = prev
        self.next = next

        # preserve the original links for undo
        assert before.next is not None and after.prev is not None
        self.unlinked_first: Piece = before.next
        self.unlinked_last: Piece = after.prev
        self.unlinked_empty = before.next == after
        assert self.unlinked_first.prev == before and self.unlinked_last.next == after

        assert after is not None and before.next is not None
        d = Location(after).distance_after(Location(before.next))
        assert d is not None and d >= (
            (0 if self.pre is None else len(self.pre))
            + (0 if self.post is None else len(self.post))
        ), f"Edit excluding insert is no longer than before {d}"

        pieces: list[Piece] = [
            p for p in cast(list[Piece|None], [self.pre, self.ins, self.post])
            if p is not None
        ]

        # link up the new pieces
        for pair in zip(pieces[:-1], pieces[1:]):
            Piece.link(*pair)

        # set up the backlinks
        if pieces:
            pieces[0].prev = before
            pieces[-1].next = after

        self._applied = False
        self.redo()

    @property
    def before(self) -> Piece:
        p = self.unlinked_first.prev if not self.unlinked_empty else self.unlinked_last
        assert p
        return p

    @property
    def after(self) -> Piece:
        p = self.unlinked_last.next if not self.unlinked_empty else self.unlinked_first
        assert p
        return p

    def undo(self) -> Location:
        """Undo this edit"""
        assert self._applied, "undo: Edit already undone"
        self.before.next = self.unlinked_first
        self.after.prev = self.unlinked_last
        self._applied = False
        return self.get_change_end()

    def redo(self) -> Location:
        """Redo this edit"""
        assert not self._applied, "redo: Edit already applied"
        self.before.next = self.pre or self.ins or self.post or self.after
        self.after.prev = self.post or self.ins or self.pre or self.before
        self._applied = True
        return self.get_change_end()


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
            left, right = pt, pt
        else:
            loc = pt.move(delete)
            left, right = (loc, pt) if delete < 0 else (pt, loc)

        pre = left.piece.lsplit(left.offset) if left.offset else None
        post = right.piece.rsplit(right.offset) if right.offset else None

        before, after = left.piece.prev, right.piece.next if right.offset else right.piece

        ins = PrimaryPiece(data=insert) if insert else None

        assert before is not None and after is not None
        edit = self.__class__(before=before, after=after, pre=pre, post=post, ins=ins, prev=self)
        self.next = edit
        return edit

    def get_change_start(self) -> Location:
        """
        The edit starts after pre, or the equivalent offset if undone
        """
        assert self.before.next
        loc = Location(self.before.next)
        if self.pre is not None:
            loc = loc.move(len(self.pre))
        return loc

    def get_change_end(self) -> Location:
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
        if self.prev is None or pt != self.get_change_end():
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
                before = self.unlinked_first.prev
                after = self.unlinked_last.next
                assert before and after
                Piece.link(self.pre or before, self.ins)
                Piece.link(self.ins, self.post or after)

        return self
