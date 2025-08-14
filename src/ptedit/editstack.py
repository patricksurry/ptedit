from __future__ import annotations
from dataclasses import dataclass

from .piece import Piece, PrimaryPiece, SecondaryPiece
from .location import Location

@dataclass
class Edit:
    before: Piece
    after: Piece
    pre: SecondaryPiece | None = None
    ins: PrimaryPiece | None = None
    post: SecondaryPiece | None = None

    def __post_init__(self):
        # preserve the original links for undo
        self._links = (self.before.next, self.after.prev)

        assert (
            Location.span_length(Location(self.before.next), Location(self.after))
            >= (0 if not self.pre else self.pre.length) + (0 if not self.post else self.post.length)
        ), "Edit excluding insert is no longer than before"

        pieces = list(filter(None, [
            self.before,
            self.pre,
            self.ins,
            self.post,
            self.after,
        ]))
        assert pieces, "Edit: empty!"
        # link up the new pieces
        for pair in zip(pieces[:-1], pieces[1:]):
            Piece.link(*pair)
        self._applied = True

    def _swap(self):
        links = self.before.next, self.after.prev
        self.before.next, self.after.prev = self._links
        self._links = links
        self._applied = not self._applied

    def location(self) -> Location:
        """
        The location of the edit is after ins and before post,
        or the equivalent offset prior to after when undone
        """
        loc = Location(self.after)
        if self.post:
            # When applied this is just Location(self.post)
            # but after an undo, we need to move an equivalent length backward
            loc = loc.move(-self.post.length)
        return loc

    def undo(self) -> Location:
        self._swap()
        assert not self._applied, "undo: Edit already undone"
        return self.location()

    def redo(self) -> Location:
        self._swap()
        assert self._applied, "redo: Edit already applied"
        return self.location()

class EditStack:
    """
    A list of edits that have been applied.
    Normally sp is the size of the edit list,
    but undo/redo navigate up/down the stack without removing later edits.
    A push (even with None value) truncates the list.
    """
    def __init__(self):
        self.edits = []
        self.sp = 0         # index of next empty slot

    def __len__(self):
        return len(self.edits)

    def push(self, edit: Edit | None) -> EditStack:
        self.edits = self.edits[:self.sp]
        if edit:
            self.edits.append(edit)
        self.sp = len(self.edits)
        return self

    def peek(self) -> Edit | None:
        return self.edits[self.sp-1] if self.sp else None

    def undo(self) -> Location | None:
        if self.sp > 0:
            self.sp -= 1
            return self.edits[self.sp].undo()
        else:
            return None

    def redo(self) -> Location | None:
        if self.sp < len(self.edits):
            self.sp += 1
            return self.edits[self.sp-1].redo()
        else:
            return None

