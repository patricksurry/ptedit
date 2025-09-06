# The layout engine for showing a document on screen
from typing import TYPE_CHECKING
import logging

from .piecetable import Document, whitespace
from .location import Location
from .formatter import Formatter
from .screen import Screen


class Display:
    def __init__(
            self,
            doc: Document,
            scr: Screen,
            fname: str = '',
            guard_rows: int=3,
            preferred_row: int=0,
            tab: int=4,
        ):
        self.scr = scr
        self.doc = doc
        self.fname = fname  # for status line
        self.rows = self.scr.height - 1     # one for status
        self.cols = self.scr.width

        self.fmt = Formatter(self.doc, self.cols, self.rows//2, tab)

        # layout options
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row if preferred_row else ((self.rows // 2) - 1)
        self.preferred_top: Location | None = None

        self.message = ''
        self.doc.watch(self.change_handler)

    def change_handler(self, start: Location, end: Location):
        self.fmt.change_handler(start, end)

    ### External interface begins

    def recenter(self):
        """Force point back to preferred row by invalidating sticky top"""
        self.preferred_top = None

    def show_message(self, msg: str, warn: bool=False):
        self.message = msg
        if warn:
            self.scr.alert()

    def move_start_line(self):
        self.fmt.clamp_to_bol()

    def move_end_line(self):
        self.fmt.clamp_to_bol()
        self.fmt.bol_to_next_bol()
        if not self.doc.at_end():
            self.doc.move_point(-1)

    def move_forward_line(self):
        self.fmt.clamp_to_bol()
        self.fmt.bol_to_next_bol()
        self.fmt.bol_to_preferred_col()

    def move_backward_line(self):
        self.fmt.clamp_to_bol()
        self.fmt.bol_to_prev_bol()
        self.fmt.bol_to_preferred_col()

    def move_forward_page(self):
        self.fmt.clamp_to_bol()
        for _ in range(self.rows):
            self.fmt.bol_to_next_bol()
        self.fmt.bol_to_preferred_col()

    def move_backward_page(self):
        self.fmt.clamp_to_bol()
        for _ in range(self.rows):
            self.fmt.bol_to_prev_bol()
        self.fmt.bol_to_preferred_col()


    def status_message(self, cursor: tuple[int, int]) -> str:
        if self.message:
            status = self.message
            self.message = ''
        else:
            pt = self.doc.get_point()
            doc_nl = self.doc.get_data().count('\n')
            pt_nl = self.doc.get_data(None, pt).count('\n')
            fname = ('*' if self.doc.dirty else '') + f'{self.fname}'
            status = "  ".join([
                f"{fname}",
                f"xy {cursor[1]},{cursor[0]}",
                f"ch ${ord(self.doc.get_char() or '\0'):02x}",
                f"pos {pt.position()}/{len(self.doc)}",
                f"lns {pt_nl}/{doc_nl}",
                f"pcs {pt.chain_length()}/{self.doc.piece_count()}",
                f"eds {self.doc.edit_stack.sp}/{len(self.doc.edit_stack.edits)}",
            ])

        return " " + status + " " * (self.cols - len(status))

    def find_top(self):
        """
        Move the point to the top left of the screen,
        anchoring to preferred_top if possible.
        """
        if TYPE_CHECKING:
            # pylance doesn't know rows > preferred_row > 0
            k = 0
            fallback = self.doc.get_point()

        self.fmt.clamp_to_bol()
        for k in range(1,self.rows+1):
            self.fmt.bol_to_prev_bol()
            if k == self.preferred_row:
                fallback = self.doc.get_point()
            if self.doc.get_point() == self.preferred_top:
                break

        # found top?
        if k < self.rows:
            # too close to point?
            while k < self.guard_rows:
                self.fmt.bol_to_prev_bol()
                k += 1

            # found top too far from point?
            while k >= self.rows - self.guard_rows:
                self.fmt.bol_to_next_bol()
                k -= 1
        else:
            self.doc.set_point(fallback)

        self.preferred_top = self.doc.get_point()

    def paint(self, mark: Location|None=None):
        """
        Paint the buffer to the screen, returning the new top-left location.
        Leaves point unchanged.
        """
        _n0 = self.doc.n_get_char_calls

        logging.info(f'paint top {len(self.fmt.bol_ladder)} bol')

        pt = self.doc.get_point()
        self.find_top()         # move point to show at top-left of screen

        _n = self.doc.n_get_char_calls - _n0
        logging.info(f'paint glyphs {len(self.fmt.bol_ladder)} bol {_n} chars, top/pt {self.doc.get_point().position()}/{pt.position()}')

        self.scr.clear()        # move cursor to 0,0

        g = self.fmt.iter_glyphs()
        cursor = (0, 0)

        highlight = mark is not None and mark.position() < self.doc.get_point().position()

        while True:
            # if we're at the point, cursor appears on next glyph

            at_point = self.doc.get_point() == pt

            if self.doc.get_point() == mark:
                highlight = not highlight

            g = self.fmt.next_glyph(g)

            if at_point:
                cursor = (g.row, g.col)
                if mark:
                    highlight = not highlight

            if g.width == 0 or g.row == self.rows:
                break

            ch = 32 if g.c in whitespace else ord(g.c)
            for _ in range(g.width):
                self.scr.put(ch, highlight=highlight)

        self.doc.set_point(pt)

        self.fmt.set_preferred_col(cursor[1])

        status = self.status_message(cursor)
        self.scr.move(self.rows, 0)
        self.scr.puts(status, highlight=True)

        self.scr.move(*cursor)
        self.scr.refresh()

        _n = self.doc.n_get_char_calls - _n - _n0
        logging.info(f'paint end {len(self.fmt.bol_ladder)} bol {_n} chars')

