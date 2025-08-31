from .piecetable import Document, MatchMode, whitespace
from .location import Location
from .display import Display


class Editor:
    def __init__(self, doc: Document, pager: Display):
        self.doc = doc

        self.doc.watch(self.change_handler)
        self.pager = pager

        # state
        self.mark: Location | None = None
        self.clipboard = ''
        self.overwrite_mode = False
        self.isearch_direction = 0      # -1 is backward, 1 is forward
        # TODO cycle mode action
        self.match_mode = MatchMode.SMART_CASE

    def change_handler(self, start: Location, end: Location):
        self.mark = None

    def squash(self):
        pos = self.doc.get_point().position()
        self.doc.squash()
        self.doc.set_point(self.doc.get_start().move(pos))

    ### Navigation commands
    def move_forward_char(self):
        self.doc.move_point(1)

    def move_backward_char(self):
        self.doc.move_point(-1)

    def move_forward_word(self):
        self.doc.find_char_forward(whitespace)
        self.doc.find_not_char_forward(whitespace)

    def move_backward_word(self):
        self.doc.find_not_char_backward(whitespace)
        self.doc.find_char_backward(whitespace)

    def move_forward_para(self):
        while not self.doc.at_end():
            self.doc.find_char_forward('\n')
            self.doc.move_point(1)
            if self.doc.get_char() in whitespace:
                break
        self.doc.find_not_char_forward(whitespace)

    def move_backward_para(self):
        self.doc.find_not_char_backward(whitespace)
        while not self.doc.at_start():
            self.doc.find_char_backward('\n')
            if self.doc.get_char() in whitespace:
                break
            self.doc.move_point(-1)
        self.doc.find_not_char_forward(whitespace)

    # Nb. line-oriented commands are implemented by renderer

    def move_start(self):
        self.doc.set_point(self.doc.get_start())

    def move_end(self):
        self.doc.set_point(self.doc.get_end())

    def set_mark(self):
        self.mark = self.doc.get_point()

    def clear_mark(self):
        self.mark = None

    def isearch_forward(self):
        self._isearch_trigger(1)

    def isearch_backward(self):
        self._isearch_trigger(-1)

    def isearch_exit(self):
        self.isearch_direction = 0
        self.clear_mark()

    def isearch_cancel(self):
        self.isearch_exit()
        self.doc.set_point(self.search_pt)

    def _isearch_insert(self, c: str):
        self.search_text += c
        self._isearch_trigger(reset=True)

    def _isearch_delete(self):
        self.search_text = self.search_text[:-1]
        self._isearch_trigger(reset=True)

    def _isearch_trigger(self, direction: int=0, reset: bool=False):
        if reset:
            self.doc.set_point(self.search_pt)

        first = self.isearch_direction == 0

        if direction:
            self.isearch_direction = direction

        if first:
            # remember where we started
            self.search_pt = self.doc.get_point()
            # TODO remember past text
            self.search_text = ''
        elif self.search_text:
            # search from current point
            if self.isearch_direction == 1:
                match = self.doc.find_forward(self.search_text, self.match_mode)
            else:
                match = self.doc.find_backward(self.search_text, self.match_mode)
            if match:
                self.mark = self.doc.get_point().move(-len(self.search_text))
        else:
            # TODO recycle past text if available
            self.pager.show_message("Empty search", True)
            # TODO quit isearch mode?

    ### Editing commands

    def toggle_overwrite(self):
        self.overwrite_mode = not self.overwrite_mode

    def insert(self, ch: int):
        c = chr(ch)
        if self.isearch_direction:
            self._isearch_insert(c)
        elif self.overwrite_mode:
            self.doc.replace(c)
        else:
            self.doc.insert(c)

    def delete_forward_char(self):
        self.doc.delete(1)

    def delete_backward_char(self):
        if self.isearch_direction:
            self._isearch_delete()
        else:
            self.doc.delete(-1)

    def _clip(self, cut: bool=False) -> str:
        if self.mark is None:
            self.pager.show_message('No mark', True)
            s = ''
        else:
            a, b = (self.mark, self.doc.get_point())
            sign = -1
            if b < a:
                (a, b) = (b, a)
                sign = 1

            s = self.doc.get_data(a, b)
            if cut:
                self.doc.delete(sign * len(s))
            self.mark = None
        return s

    def copy(self):
        self.clipboard = self._clip(cut=False)

    def cut(self):
        self.clipboard = self._clip(cut=True)

    def paste(self):
        if not self.clipboard:
            self.pager.show_message('Clipboard empty', True)
            return
        if self.mark:
            _ = self._clip(cut=True)
        self.doc.insert(self.clipboard)

    def _clip_line(self, cut: bool=False) -> str:
        self.pager.move_start_line()
        self.mark = self.doc.get_point()
        self.pager.move_end_line()
        return self._clip(cut)

    def copy_line(self):
        """Copy line to clipboard"""
        self.clipboard = self._clip_line(False)

    def cut_line(self):
        """Cut line to clipboard"""
        self.clipboard = self._clip_line(True)

    def undo(self):
        self.doc.undo()

    def redo(self):
        self.doc.redo()


