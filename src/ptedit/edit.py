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
        exclude_first: Piece,
        exclude_last: Piece,

        # The Edit contains 0-3 new pieces pre/ins/post describing the new fragment
        pre: SecondaryPiece | None = None,
        ins: PrimaryPiece | None = None,     # for an insertion when new data is created
        post: SecondaryPiece | None = None,

        # Edits form a linked list supporting undo/redo
        prev: Self | None = None,
        next: Self | None = None,
    ):
        """
        The constructor is private.
        Use Edit.create() to create a new edit for a change,
        or edit.apply_change() to merge a compatible change if possible, otherwise appending a new edit
        """

        self.pre = pre
        self.post = post
        self.ins = ins
        self.prev = prev
        self.next = next

        # preserve the original links for undo
        self.exclude_first: Piece = exclude_first
        self.exclude_last: Piece = exclude_last
        self.exclude_empty = exclude_first == exclude_last.next

        assert exclude_first is not None and exclude_last.next is not None
        d = Location(exclude_last.next).distance_after(Location(exclude_first))
        assert d is not None and d >= (
            (0 if self.pre is None else len(self.pre))
            + (0 if self.post is None else len(self.post))
        ), f"Edit excluding insert should not be longer than before change, got d={d}"

        pieces: list[Piece] = [
            p for p in cast(list[Piece|None], [self.pre, self.ins, self.post])
            if p is not None
        ]

        # link up the new pieces
        for pair in zip(pieces[:-1], pieces[1:]):
            Piece.link(*pair)

        # set up the backlinks
        if pieces:
            pieces[0].prev = self.before
            pieces[-1].next = self.after

        self._applied = False
        self.redo()

    @property
    def before(self) -> Piece:
        p = self.exclude_first.prev if not self.exclude_empty else self.exclude_last
        assert p
        return p

    @property
    def after(self) -> Piece:
        p = self.exclude_last.next if not self.exclude_empty else self.exclude_first
        assert p
        return p

    @classmethod
    def create(cls, pt: Location, delete: int = 0, insert: str = '') -> Self:
        """Create an edit representing an insert/delete action"""
        if delete == 0:
            left, right = pt, pt
        else:
            loc = pt.move(delete)
            left, right = (loc, pt) if delete < 0 else (pt, loc)

        exclude_first, exclude_last = left.piece, right.piece if right.offset else right.piece.prev
        assert exclude_first and exclude_last

        pre = left.piece.lsplit(left.offset) if left.offset else None
        post = right.piece.rsplit(right.offset) if right.offset else None
        ins = PrimaryPiece(data=insert) if insert else None

        return cls(exclude_first, exclude_last, pre=pre, post=post, ins=ins)

    def apply_change(self, pt: Location, delete: int = 0, insert: str = '') -> Self:
        """
        Either update self or return a new Edit
        """
        compatible = True
        if self.prev is None or pt != self.get_change_end():
            compatible = False
        elif delete:
            p = self.post if delete > 0 else (self.ins or self.pre)
            if not p or len(p) <= abs(delete):
                compatible = False
            else:
                p.trim(delete)

        if not compatible:
            return self.append(self.create(pt, delete, insert))

        if insert:
            if self.ins:
                self.ins.extend(insert)
            else:
                self.ins = PrimaryPiece(data=insert)
                Piece.link(self.pre or self.before, self.ins)
                Piece.link(self.ins, self.post or self.after)

        return self

    def append(self, edit: Self) -> Self:
        edit.prev = self
        self.next = edit
        return edit

    def undo(self) -> Location:
        """Undo this edit"""
        assert self._applied, "undo: Edit already undone"
        self.before.next = self.exclude_first
        self.after.prev = self.exclude_last
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

