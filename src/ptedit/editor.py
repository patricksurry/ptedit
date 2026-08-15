from __future__ import annotations
from enum import IntEnum
from typing import Callable
from .document import Document, MatchMode, whitespace
from .location import Location
from .layout import Layout


NotifyFn = Callable[[str, bool], None]


class ISearchDirection(IntEnum):
    FORWARD = 1
    BACKWARD = -1


class Editor:
    def __init__(self, doc: Document, layout: Layout, notify: NotifyFn) -> None:
        self.doc = doc
        self.layout = layout
        self.notify = notify

        # state
        self.mark: Location | None = None
        self.clipboard: str = ''
        self.overwrite_mode: bool = False
        self.isearch_dir: ISearchDirection | None = None
        self.isearch_text: str = ''
        self.isearch_origin: Location = self.doc.get_point()
        # isearch_start is true on the first key after C-S/C-R; while true,
        # any new typed character clears the previous search text.  This is
        # what lets `C-S C-S` repeat the prior search: the second C-S leaves
        # isearch_text intact, but typing a new character starts fresh.
        self.isearch_start: bool = False

        # TODO cycle mode action
        self.match_mode: MatchMode = MatchMode.SMART_CASE

        # Facade: line/page motion is a buffer command, exposed under `ed`.
        # The mechanism (ladder, goal column) stays in Layout — this delegates,
        # it does not relocate.
        self.move_line_start = layout.move_line_start
        self.move_line_end = layout.move_line_end
        self.move_line_forward = layout.move_line_forward
        self.move_line_backward = layout.move_line_backward
        self.move_page_forward = layout.move_page_forward
        self.move_page_backward = layout.move_page_backward

    def squash(self) -> None:
        self.mark = None            # locations don't survive chain surgery
        pos = self.doc.get_point().position()
        self.doc.squash()
        self.doc.set_point_start().move_point(pos)

    ### Navigation commands

    def move_char_forward(self) -> None:
        self.doc.move_point(1)

    def move_char_backward(self) -> None:
        self.doc.move_point(-1)

    def move_word_forward(self) -> None:
        self.doc.find_char_forward(whitespace)
        self.doc.find_not_char_forward(whitespace)

    def move_word_backward(self) -> None:
        self.doc.find_not_char_backward(whitespace)
        self.doc.find_char_backward(whitespace)

    def move_para_forward(self) -> None:
        while not self.doc.at_end():
            self.doc.find_char_forward('\n')
            self.doc.move_point(1)
            if self.doc.get_char() in whitespace:
                break
        self.doc.find_not_char_forward(whitespace)

    def move_para_backward(self) -> None:
        self.doc.find_not_char_backward(whitespace)
        while not self.doc.at_start():
            self.doc.find_char_backward('\n')
            if self.doc.get_char() in whitespace:
                break
            self.doc.move_point(-1)
        self.doc.find_not_char_forward(whitespace)

    # Nb. line-oriented commands are implemented by renderer

    def move_doc_start(self) -> None:
        self.doc.set_point_start()

    def move_doc_end(self) -> None:
        self.doc.set_point_end()

    def set_mark(self) -> None:
        self.mark = self.doc.get_point()

    def clear_mark(self) -> None:
        self.mark = None

    def isearch_forward(self) -> None:
        self._isearch_go(ISearchDirection.FORWARD)

    def isearch_backward(self) -> None:
        self._isearch_go(ISearchDirection.BACKWARD)

    def isearch_exit(self) -> None:
        """Exit, leaving point after last search"""
        self.isearch_dir = None
        self.mark = None

    def isearch_cancel(self) -> None:
        """Exit, returning to the original point"""
        self.isearch_exit()
        self.doc.set_point(self.isearch_origin)

    def isearch_insert(self, c: str) -> None:
        """Extend search text and restart search"""
        if self.isearch_start:      # defer clearing search text to allow reuse with C-S C-S
            self.isearch_text = ''
        self.isearch_text += c
        self._isearch_restart()

    def isearch_delete(self) -> None:
        """Trim search text and restart search"""
        if self.isearch_start:
            self.isearch_text = ''
        self.isearch_text = self.isearch_text[:-1]
        self._isearch_restart()

    def _isearch_restart(self) -> None:
        self.doc.set_point(self.isearch_origin)
        self._isearch_go()

    def _isearch_go(self, direction: ISearchDirection | None = None) -> None:
        self.isearch_start = self.isearch_dir is None

        if direction is not None:
            self.isearch_dir = direction

        self.notify(f"Search: {self.isearch_text}", False)
        self.mark = None

        if self.isearch_start:
            # starting a new search
            self.isearch_origin = self.doc.get_point()
            return

        if self.isearch_text:
            # search from current point
            if self.isearch_dir == ISearchDirection.FORWARD:
                match = self.doc.find_forward(self.isearch_text, self.match_mode)
            else:
                match = self.doc.find_backward(self.isearch_text, self.match_mode)
            # highlight match if found
            if match:
                self.mark = self.doc.get_point().move(-len(self.isearch_text))
        else:
            self.notify("Empty search", True)

    ### Editing commands

    def toggle_overwrite(self) -> None:
        self.overwrite_mode = not self.overwrite_mode

    def _kill_region(self) -> None:
        """Delete marked region in place; does NOT touch the clipboard."""
        if self.mark is None:
            return
        a, b = self.mark, self.doc.get_point()
        if b.is_at_or_before(a):
            a, b = b, a
        n = b.position() - a.position()
        self.doc.set_point(b)
        self.doc.delete(-n)
        self.mark = None

    def _clip_region(self, cut: bool = False) -> str:
        """Cut or copy marked region, error if no mark"""
        if self.mark is None:
            self.notify('No mark', True)
            s = ''
        else:
            a, b = (self.mark, self.doc.get_point())
            sign = -1
            if b.is_at_or_before(a):
                (a, b) = (b, a)
                sign = 1

            s = self.doc.get_data(a, b)
            if cut:
                self.doc.delete(sign * len(s))
            self.mark = None
        return s

    def insert(self, ch: int) -> None:
        self._kill_region()
        c = chr(ch)
        if self.overwrite_mode:
            self.doc.replace(c)
        else:
            self.doc.insert(c)

    def delete_char_forward(self) -> None:
        self._kill_region()
        self.doc.delete(1)

    def delete_char_backward(self) -> None:
        self._kill_region()
        self.doc.delete(-1)

    def copy(self) -> None:
        self.clipboard = self._clip_region(cut=False)

    def cut(self) -> None:
        self.clipboard = self._clip_region(cut=True)

    def paste(self) -> None:
        if not self.clipboard:
            self.notify('Clipboard empty', True)
            return
        self._kill_region()
        self.doc.insert(self.clipboard)

    def _clip_line(self, cut: bool = False) -> str:
        self.layout.move_line_start()
        self.mark = self.doc.get_point()
        self.layout.move_line_end()
        self.move_char_forward()
        return self._clip_region(cut)

    def copy_line(self) -> None:
        """Copy line to clipboard"""
        self.clipboard = self._clip_line(False)

    def cut_line(self) -> None:
        """Cut line to clipboard"""
        self.clipboard = self._clip_line(True)

    def undo(self) -> None:
        self.mark = None            # locations don't survive chain surgery
        self.doc.undo()

    def redo(self) -> None:
        self.mark = None
        self.doc.redo()


