import logging
logging.basicConfig(filename='controller.log', filemode='w', level=logging.DEBUG)

from .piecetable import Document
from .location import Location
from .renderer import Renderer, whitespace


class Editor:
    def __init__(self, doc: Document, rdr: Renderer):
        self.doc = doc
        self.rdr = rdr

        self.doc.watch(self.mutating)

        # state
        self.mark: Location | None = None
        self.clipboard = ''
        self.overwrite_mode = False
        self.isearch_direction = 0      # -1 is backward, 1 is forward

    def quit(self):
        self.doc = None         # TODO flag main to exit

    def save(self):
        self.doc.save()

    def mutating(self):
        self.mark = None

    def squash(self):
        self.doc.squash()

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
        while self.doc.get_point() != self.doc.get_end():
            self.doc.find_char_forward('\n')
            self.doc.move_point(1)
            if self.doc.get_char() in whitespace:
                break
        self.doc.find_not_char_forward(whitespace)

    def move_backward_para(self):
        self.doc.find_not_char_backward(whitespace)
        while self.doc.get_point() != self.doc.get_start():
            self.doc.find_char_backward('\n')
            if self.doc.get_char() in whitespace:
                break
            self.doc.move_point(-1)
        self.doc.find_not_char_forward(whitespace)

    def move_start_line(self):
        self.rdr.clamp_to_bol()

    def move_end_line(self):
        self.rdr.clamp_to_bol()
        self.rdr.bol_to_next_bol()
        self.move_backward_char()

    def move_forward_line(self):
        self.rdr.clamp_to_bol()
        self.rdr.bol_to_next_bol()
        self.rdr.bol_to_preferred_col()

    def move_backward_line(self):
        self.rdr.clamp_to_bol()
        self.rdr.bol_to_prev_bol()
        self.rdr.bol_to_preferred_col()

    def move_forward_page(self):
        self.rdr.clamp_to_bol()
        for _ in range(self.rdr.rows):
            self.rdr.bol_to_next_bol()
        self.rdr.bol_to_preferred_col()

    def move_backward_page(self):
        self.rdr.clamp_to_bol()
        for _ in range(self.rdr.rows):
            self.rdr.bol_to_prev_bol()
        self.rdr.bol_to_preferred_col()

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

    def _isearch_trigger(self, direction=0, reset=False):
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
                match = self.doc.find_forward(self.search_text)
            else:
                match = self.doc.find_backward(self.search_text)
            if match:
                self.mark = self.doc.get_point().move(-len(self.search_text))
        else:
            # TODO recycle past text if available
            self.show_error("Empty search")
            # TODO quit isearch mode?

    ### Editing commands

    def toggle_overwrite(self):
        self.overwrite_mode = not self.overwrite_mode

    def insert(self, ch):
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

    def _clip(self, cut=False) -> str:
        if not self.mark:
            self.rdr.show_error('no mark')
            s = ''
        else:
            a, b = (self.mark, self.doc.get_point())
            #TODO some kind of a precedes b function
            sign = -1
            if Location.span_contains(a, b, self.doc.get_end()):
                (a, b) = (b, a)
                sign = 1

            s = Location.span_data(a, b)
            if cut:
                self.doc.delete(sign * Location.span_length(a, b))
            self.mark = None
        return s

    def copy(self):
        self.clipboard = self._clip(cut=False)

    def cut(self):
        self.clipboard = self._clip(cut=True)

    def paste(self):
        if not self.clipboard:
            self.rdr.show_error('empty clipboard')
            return
        if self.mark:
            _ = self._clip(cut=True)
        self.doc.insert(self.clipboard)

    def undo(self):
        self.doc.undo()

    def redo(self):
        self.doc.redo()


