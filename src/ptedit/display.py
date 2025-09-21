# The layout engine for showing a document on screen
from typing import TYPE_CHECKING
import logging

from .document import Document
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

        self.preferred_col = 0          # last column that wasn't
        self.pin_preferred_col = False  # True if cursor should track preferred col

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
            logging.warning(msg)

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
        # defer column setting until we render the line with the point
        self.pin_preferred_col = True

    def move_backward_line(self):
        self.fmt.clamp_to_bol()
        self.fmt.bol_to_prev_bol()
        self.pin_preferred_col = True

    def move_forward_page(self):
        self.fmt.clamp_to_bol()
        for _ in range(self.rows):
            self.fmt.bol_to_next_bol()
        self.pin_preferred_col = True

    def move_backward_page(self):
        self.fmt.clamp_to_bol()
        for _ in range(self.rows):
            self.fmt.bol_to_prev_bol()
        self.pin_preferred_col = True

    def status_message(self, cursor: tuple[int, int]) -> str:
        if self.message:
            status = self.message
            self.message = ''
        else:
            pt = self.doc.get_point()
            doc_nl = self.doc.get_data().count('\n')
            pt_nl = self.doc.get_data(None, pt).count('\n')
            fname = ('*' if self.doc.dirty else '') + f'{self.fname}'
            pt_pieces, all_pieces = self.doc.piece_counts()
            pt_edits, all_edits = self.doc.edit_counts()
            status = "  ".join([
                f"{fname}",
                f"xy {cursor[1]},{cursor[0]}",
                f"ch ${ord(self.doc.get_char() or '\0'):02x}",
                f"pos {pt.position()}/{len(self.doc)}",
                f"lns {pt_nl}/{doc_nl}",
                f"pcs {pt_pieces}/{all_pieces}",
                f"eds {pt_edits}/{all_edits}",
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

        original_pt = self.doc.get_point()
        self.find_top()         # move point to show at top-left of screen

        _n = self.doc.n_get_char_calls - _n0
        logging.info(f'paint glyphs {len(self.fmt.bol_ladder)} bol {_n} chars, top/pt {self.doc.get_point().position()}/{original_pt.position()}')

        self.scr.clear()        # move cursor to 0,0

        cursor = (0, 0)

        start_pt = self.doc.get_point()
        start_pos = start_pt.position()
        pt_off = original_pt.position() - start_pos
        assert pt_off >= 0, "Point should always be on screen"
        mark_off = (mark if mark else original_pt).position()  - start_pos

        highlight = mark_off < 0

        row = 0
        while row < self.rows and not self.doc.at_end():
            line = self.fmt.format_line()
            pt = self.doc.get_point()
            delta = pt.distance_after(start_pt)
            assert delta is not None
            start_pt = pt
            toggle = bytearray(self.cols)
            if 0 <= pt_off < delta:
                if self.pin_preferred_col:
                    assert pt_off == 0
                    # deferred move forward to pinned column
                    pt_off = self.fmt.offset_for_column(self.pin_preferred_col, line)
                    assert pt_off < delta
                    original_pt = original_pt.move(pt_off)
                col = self.fmt.column_for_offset(pt_off, line)
                toggle[col] = 1 - toggle[col]
                cursor = (row, col)

            if 0 <= mark_off < delta:
                col = self.fmt.column_for_offset(mark_off, line)
                toggle[col] = 1 - toggle[col]

            pt_off -= delta
            mark_off -= delta

            for col, ch in enumerate(line):
                if toggle[col]:
                    highlight = not highlight
                match ch:
                    case 1: ch = ord('^')
                    case 2: ch = ord('\\')
                    case _ if ch < 32: ch = ord(' ')
                    case _: pass
                self.scr.put(ch, highlight)

            row += 1

        self.doc.set_point(original_pt)

        if not self.pin_preferred_col:
            self.preferred_col = cursor[1]
        else:
            self.pin_preferred_col = False

        status = self.status_message(cursor)
        self.scr.move(self.rows, 0)
        self.scr.puts(status, highlight=True)

        self.scr.move(*cursor)
        self.scr.refresh()

        _n = self.doc.n_get_char_calls - _n - _n0
        logging.info(f'paint end {len(self.fmt.bol_ladder)} bol {_n} chars')

