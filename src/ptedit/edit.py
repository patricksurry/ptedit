from __future__ import annotations
from dataclasses import dataclass

from .piece import Piece, PrimaryPiece, SecondaryPiece


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
        self._done = True

    def _swap(self):
        links = self.before.next, self.after.prev
        self.before.next, self.after.prev = self._links
        self._links = links
        self._done = not self._done

    def undo(self):
        self._swap()
        assert not self._done, "undo: Edit already undone"

    def redo(self):
        self._swap()
        assert self._done, "redo: Edit already done"


class EditStack:
    """
    A list of edits that have been applied.
    Normally sp is the size of the edit list,
    but undo/redo navigate up/down the stack without removing later edits.
    A push (even with None value) truncates the list.
    """
    def __init__(self):
        self.edits = []
        self.sp = 0         # point to next empty slot

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

    def undo(self):
        self.sp -= 1
        if self.sp >= 0:
            self.edits[self.sp].undo()

    def redo(self):
        if self.sp < len(self.edits):
            self.edits[self.sp].redo()
        self.sp += 1


