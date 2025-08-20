from typing import Callable
from dataclasses import dataclass

import logging
logging.basicConfig(filename='controller.log', filemode='w', level=logging.DEBUG)

from .piecetable import Document
from .location import Location
from .renderer import Renderer, whitespace

KeyFn = Callable[['Editor'],None]
KeyMap = dict[int, KeyFn]




def mutator(method):
    def wrapped(self, *args):
        self.mutating()
        method(self, *args)
    return wrapped


class Editor:
    def __init__(self,
            doc: Document,
            rdr: Renderer,
            fname='',
        ):
        self.doc = doc
        self.rdr = rdr

        self.fname = fname

        # state
        self.mark: Location | None = None
        self.overwrite_mode = False
        self.isearch_direction = 0      # -1 is backward, 1 is forward

        self.dirty = False              # saved since last change?

    #TODO this should be in document
    def save(self):
        if self.fname:
            open(self.fname, 'w').write(self.doc.data)
        self.dirty = False

    def quit(self):
        self.doc = None         # TODO flag main to exit

    #TODO this should really be notified by document to listeners
    def mutating(self):
        self.dirty = True
        self.mark = None
        self.rdr.mutating()

    @mutator
    def squash(self):
        self.doc = Document(self.doc.data)

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

    @mutator
    def insert(self, ch):
        c = chr(ch)
        if self.isearch_direction:
            self._isearch_insert(c)
        elif self.overwrite_mode:
            self.doc.replace(c)
        else:
            self.doc.insert(c)

    @mutator
    def delete_forward_char(self):
        self.doc.delete(1)

    @mutator
    def delete_backward_char(self):
        if self.isearch_direction:
            self._isearch_delete()
        else:
            self.doc.delete(-1)

    @mutator
    def undo(self):
        self.doc.undo()

    @mutator
    def redo(self):
        self.doc.redo()


