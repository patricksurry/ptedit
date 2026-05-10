# The view layer: paints lines from Layout onto a Screen and tracks scroll state.
import logging

from .document import Document
from .location import Location
from .layout import Layout
from .screen import Screen


class Display:
    def __init__(
            self,
            doc: Document,
            scr: Screen,
            guard_rows: int=3,
            preferred_row: int=0,
            tab: int=4,
        ):
        self.scr = scr
        self.doc = doc
        self.rows = self.scr.height - 1     # one for status
        self.cols = self.scr.width

        self.layout = Layout(self.doc, self.cols, self.rows, self.rows // 2, tab)

        # layout options
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row if preferred_row else ((self.rows // 2) - 1)
        self.message = ''
        self.doc.watch(self.change_handler)

    def change_handler(self, start: Location, end: Location):
        self.layout.change_handler(start, end)

    ### External interface begins

    def recenter(self):
        """Redraw screen; recentering is now implicit on every paint"""
        self.paint()

    def show_message(self, msg: str, warn: bool=False):
        self.message = msg
        if warn:
            self.scr.alert()
            logging.warning(msg)

    def find_top(self):
        """Move the point to the top-left of the screen by walking
        preferred_row visual lines back from the current point."""
        self.layout.clamp_to_bol()
        for _ in range(self.preferred_row):
            if self.doc.at_start():
                return
            self.layout.bol_to_prev_bol()

    def paint(self, mark: Location|None=None) -> tuple[int, int]:
        """
        Paint the buffer content to the screen, returning the cursor position.
        Leaves point unchanged. The caller is responsible for the status line,
        restoring the cursor, and refreshing the screen.
        """
        original_pt = self.doc.get_point()
        at_end = self.doc.at_end()

        self.find_top()         # move point to show at top-left of screen

        self.scr.clear()        # move cursor to 0,0

        cursor = (0,0)

        start_pt = self.doc.get_point()
        start_pos = start_pt.position()
        pt_off = original_pt.position() - start_pos
        assert pt_off >= 0, "Point should always be on screen"
        if mark:
            mark_off = (mark.position() - start_pos)
        else:
            mark_off = pt_off

        highlight = mark_off < 0

        row = 0
        while row < self.rows:
            line, col_map = self.layout.format_line()
            pt = self.doc.get_point()
            delta = len(col_map)
            start_pt = pt
            toggle_mark = -1
            toggle_pt = -1
            # found the point?
            logging.info(f"delta {delta} pt_off {pt_off} end {self.doc.at_end()}")
            if 0 <= pt_off < delta:
                # deferred move to preferred column?
                if not at_end and self.layout.pin_preferred_col:
                    assert pt_off == 0, f"panic: pt_off={pt_off}"
                    pt_off = self.layout.offset_for_column(self.layout.preferred_col, col_map)
                    original_pt = original_pt.move(pt_off)
                    if not mark:
                        mark_off = pt_off
                col = col_map[pt_off]
                toggle_pt = col
                cursor = (row, col)

            if 0 <= mark_off < delta:
                # found the mark?
                col = col_map[mark_off]
                toggle_mark = col

            pt_off -= delta
            mark_off -= delta

            for col, ch in enumerate(line):
                if toggle_pt == col:
                    highlight = not highlight
                if toggle_mark == col:
                    highlight = not highlight
                match ch:
                    case 1: ch = ord('^')
                    case 2: ch = ord('\\')
                    case _ if ch < 32: ch = ord(' ')
                    case _: pass
                self.scr.put(ch, highlight)

            row += 1

        self.doc.set_point(original_pt)

        if not self.layout.pin_preferred_col:
            self.layout.preferred_col = cursor[1] if not self.doc.at_end() else 0
        else:
            self.layout.pin_preferred_col = False

        return cursor

