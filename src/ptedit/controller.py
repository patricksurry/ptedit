import curses
from curses import window
from typing import Callable
from dataclasses import dataclass

import logging
logging.basicConfig(filename='controller.log', filemode='w', level=logging.DEBUG)

from .piecetable import PieceTable
from .location import Location


whitespace = ' \t\n'

KeyFn = Callable[['Controller'],None]
KeyMap = dict[int, KeyFn]


@dataclass
class Glyph:
    c: str = ''
    row: int = 0
    col: int = 0
    width: int = 0
    lookahead: bool = True

def mutator(method):
    def wrapped(self, *args):
        self.mutating()
        method(self, *args)
    return wrapped


class Controller:
    def __init__(self,
            doc: PieceTable,
            height: int,
            width: int,
            fname='',
            control_keys: KeyMap = {},
            meta_keys: KeyMap = {},
            guard_rows=4,
            preferred_row=0,
            tab=8):
        self.doc = doc
        self.height = height-1      # save last line for status
        self.width = width
        self.fname = fname

        # keymap
        self.control_keys = control_keys
        self.meta_keys = meta_keys

        # layout options
        self.tab = tab
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row or int(0.4*height)
        self.preferred_col = 0
        self.preferred_top = self.doc.get_point() # top-left of screen

        # state
        self.mark: Location|None = None
        self.overwrite_mode = False
        self.meta_mode = False
        self.isearch_direction = 0      # -1 is backward, 1 is forward
        self.is_column_sticky = True    # sticky col for vertical navigation
        self.dirty = False              # saved since last change?
        self._bols: list[Location] = [] # cached beginning of line marks

    def save(self):
        if self.fname:
            open(self.fname, 'w').write(self.doc.data)
        self.dirty = False

    def quit(self):
        self.doc = None         # TODO flag main to exit

    def mutating(self):
        self.dirty = True
        self._bols = []

    @mutator
    def squash(self):
        self.doc = PieceTable(self.doc.data)

    def show_error(self, msg: str):
        #TODO save message for status bar
        curses.flash()

    def toggle_meta(self):
        self.meta_mode = not self.meta_mode

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
        self.clamp_to_bol()

    def move_end_line(self):
        self.clamp_to_bol()
        self.bol_to_next_bol()
        self.move_backward_char()

    def move_forward_line(self):
        self.clamp_to_bol()
        self.bol_to_next_bol()
        self.bol_to_preferred_col()

    def move_backward_line(self):
        self.clamp_to_bol()
        self.bol_to_prev_bol()
        self.bol_to_preferred_col()

    def move_forward_page(self):
        self.clamp_to_bol()
        for _ in range(self.height):
            self.bol_to_next_bol()
        self.bol_to_preferred_col()

    def move_backward_page(self):
        self.clamp_to_bol()
        for _ in range(self.height):
            self.bol_to_prev_bol()
        self.bol_to_preferred_col()

    def move_start(self):
        self.doc.set_point(self.doc.get_start())

    def move_end(self):
        self.doc.set_point(self.doc.get_end())

    def isearch_forward(self):
        self._isearch_trigger(1)

    def isearch_backward(self):
        self._isearch_trigger(-1)

    def _isearch_quit(self, cancel=False):
        self.isearch_direction = 0
        if cancel:
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
                self.doc.find_forward(self.search_text)
            else:
                self.doc.find_backward(self.search_text)
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

    ### Internal beginning-of-line routines

    def _bol_forward(self, max_col: int | None = None):
        """
        Advance point from BOL to max_col or the next BOL.
        i.e. just past a newline/whitespace/hyphen or end of doc.
        """
        if max_col == 0:
            return
        elif max_col is None:
            max_col = self.width

        g = self.glyph_init()
        while True:
            g = self.glyph_next(g)
            if g.width == 0 or g.row > 0 or g.col + g.width > max_col:
                break

        # unless we're at end, unget the char that took us past the desired location
        if g.width > 0:
            self.doc.move_point(-1)

    def bol_to_preferred_col(self):
        self._bol_forward(self.preferred_col)
        self.is_column_sticky = False

    def clamp_to_bol(self):
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        pt = self.doc.get_point()
        if pt in self._bols:
            return

        self.doc.find_char_backward('\n')
        loc = self.doc.get_point()
        while loc != pt:
            prev = loc
            self.bol_to_next_bol()
            loc = self.doc.get_point()
            if Location.span_contains(pt, prev, loc):
                self.doc.set_point(prev)
                break

    def bol_to_next_bol(self):
        bol = self.doc.get_point()

        n = len(self._bols)
        try:
            i = self._bols.index(bol)
        except:
            i = n     # force miss
        if i+1 < n:
            self.doc.set_point(self._bols[i+1])
        else:
            self._bol_forward()

    def bol_to_prev_bol(self):
        """
        Move from BOL to the previous BOL.
        This is a no-op at the document start.
        """
        bol = self.doc.get_point()
        if bol == self.doc.get_start():
            return

        # when there's a _bols cache miss on the way backward, we
        # end up discarding pre-calculated BOLs for the following lines.
        # we can do extra shenanigans to presereve the old list and tack it on
        # the end of the new one created by processing this line but the extra
        # complexity doesn't seem worth it: in normal use we pay the higher backward
        # cost once, and then the forward pass painting the screen primes the cache
        # and speeds up many subsequent frames unless the user is doing a lot of
        # long-range navigation.  Without a cache we process more than 6x
        # the characters on the screen while rendering it; once the cache is primed
        # that reduces to about 10-15% overhead
        try:
            i = self._bols.index(bol)
        except:
            i = 0   # force miss

        if i > 0:
            self.doc.set_point(self._bols[i-1])
            return

        self.doc.move_point(-1)
        self.doc.find_char_backward('\n')
        while True:
            loc = self.doc.get_point()
            self.bol_to_next_bol()
            if bol == self.doc.get_point():
                break
        self.doc.set_point(loc)

    ### Key handling

    def key_handler(self, key: int):
        """Handle an ascii keypress"""
        if self.meta_mode:
            fn = self.meta_keys.get(key)
            if fn:
                fn(self)
            else:
                self.show_error(f'Unmapped meta key {key}')
            self.meta_mode = False
            return

        if 32 <= key < 127:
            # printable ascii keys insert themselves
            fn = Controller.insert
        else:
            fn = self.control_keys.get(key)

        if fn == Controller.insert:
            fn(self, key)
        elif fn:
            # is isearch active?
            if self.isearch_direction != 0 and fn not in (
                    Controller.isearch_forward,
                    Controller.isearch_backward,
                    Controller.delete_backward_char,
                ):
                # meta key cancels search and is not processed
                if fn == Controller.toggle_meta:
                    self._isearch_quit(True)
                    return
                # other actions terminate search but are still executed
                self._isearch_quit()
            fn(self)
        else:
            self.show_error(f'Unmapped key {key}')

    ### Screen update

    def find_top(self):
        """
        Move the point to the top left of the screen,
        anchoring to preferred_top if possible.
        """
        #TODO this always treats end-of-doc as new line even when there isn't
        # an actual newline
        self.clamp_to_bol()
        for k in range(self.height):
            self.bol_to_prev_bol()
            if k == self.preferred_row:
                fallback = self.doc.get_point()
            if self.doc.get_point() == self.preferred_top:
                break

        # found top?
        if k < self.height-1:
            # too close to point?
            while k < self.guard_rows:
                self.bol_to_prev_bol()
                k += 1

            # found top too far from point?
            while k > self.height - self.guard_rows:
                self.bol_to_next_bol()
                k -= 1
        else:
            self.doc.set_point(fallback)

        self.preferred_top = self.doc.get_point()

    def glyph_init(self) -> Glyph:
        pt = self.doc.get_point()
        if not self._bols or pt != self._bols[-1]:
            self._bols = [pt]
        return Glyph()

    def glyph_next(self, g: Glyph) -> Glyph:
        g.c = self.doc.next_char()
        # update from previous glyph
        g.col += g.width
        if g.col >= self.width:
            g.lookahead = True      # always safe at start of row
            g.col = 0
            g.row += 1

        if not g.c or g.c in  ' -\t\n':
            g.lookahead = False
        elif not g.lookahead:
            # not-breaking character, need to do lookahead
            pt = self.doc.get_point()
            available = self.width - g.col - 1
            while available:
                c = self.doc.next_char()
                if c in ' -\t\n':
                    break
                available -= 1
            if available:
                g.lookahead = True
            else:
                pt = pt.move(-1)    # unget the non-breaking character
                g.c = '\n'          # send a soft break instead
            self.doc.set_point(pt)

        match g.c:
            case '':
                g.width = 0
            case '\t':
                # Nb. assumes tab divides self.width
                g.width = self.tab - (g.col % self.tab)
            case '\n':
                g.width = self.width - g.col
            case _:
                g.width = 1

        if not g.c or g.width + g.col == self.width:
            self._bols.append(self.doc.get_point())

        return g

    def status_line(self, pt: Location, cursor: tuple[int, int]):
        doc_nl = self.doc.data.count('\n')
        pt_nl = Location.span_data(self.doc.get_start(), pt).count('\n')
        fname = ('*' if self.dirty else '') + f'{self.fname}'
        status = "  ".join([
            f" {fname}",
            f"xy {cursor[1]},{cursor[0]}",
            f"pos {pt.position()}/{self.doc.length}",
            f"lns {pt_nl}/{doc_nl}",
            f"pcs {pt.chain_length()}/{self.doc.get_end().chain_length()}",
            f"eds {self.doc.edit_stack.sp}/{len(self.doc.edit_stack.edits)}",
        ])
        status += " " * (self.width - len(status))
        return status

    def paint(self, scr: window):
        """
        Paint the buffer to the screen, returning the new top-left location.
        Leaves point unchanged.
        """
        pt = self.doc.get_point()
        self.find_top()         # move point to show at top-left of screen
        cursor = None           # the y,x of the point

        scr.clear()

        g = self.glyph_init()

        while True:
            # if we're at the point, cursor appears on next glyph
            at_point = self.doc.get_point() == pt

            g = self.glyph_next(g)

            if at_point:
                cursor = (g.row, g.col)

            if g.width == 0 or g.row == self.height-1:
                break

            scr.move(g.row, g.col)

            ch = 32 if g.c in whitespace else ord(g.c)
            for _ in range(g.width):
                scr.addch(ch)

        # update preferred column unless this was a non-sticky cursor movement
        if self.is_column_sticky:
            self.preferred_col = cursor[1]
        else:
            self.is_column_sticky = True

        status = self.status_line(pt, cursor)
        try:
            # ignore the error when we advance past the end of the screen
            scr.addstr(self.height, 0, status, curses.A_REVERSE)
        except curses.error:
            pass

        scr.move(*cursor)
        scr.refresh()

        logging.info(f"paint drew {Location.span_length(self.preferred_top, self.doc.get_point())}")
        self.doc.set_point(pt)
