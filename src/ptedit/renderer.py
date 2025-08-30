# The layout engine for showing a document on screen
from typing import TYPE_CHECKING
from dataclasses import dataclass
import curses
import logging


logging.basicConfig(level=logging.DEBUG, filename='ptedit.log', filemode='w')


from .piecetable import Document
from .location import Location


whitespace = ' \t\n'


@dataclass
class Screen:
    height: int
    width: int

    def clear(self):
        """clear the screen and move cursor to top-left"""
        ...

    def refresh(self):
        """refresh display"""
        ...

    def alert(self):
        """optionally alert the user, e.g. flash, bell"""
        pass

    def move(self, row: int, col: int):
        ...

    def put(self, ch: int, highlight: bool=False):
        """put character and increment position"""
        ...

    def puts(self, s: str, highlight: bool=False):
        for c in s:
            self.put(ord(c), highlight)


class CursesScreen(Screen):
    def __init__(self, win: curses.window):
        self.win = win
        self.win.scrollok(False)
        # the actual cursor shape is determined by the terminal, e.g. for OS X terminal
        # use Terminal > Settings > Text > Cursor to pick vert or horiz bar vs block etc
        curses.curs_set(2)          # 0 is invisible, 1 is normal, 2 is high-viz (e.g. block)
        self.height, self.width = self.win.getmaxyx()
        assert self.height > 1 and self.width > 0

    def clear(self):
        self.win.clear()

    def refresh(self):
        self.win.refresh()

    def move(self, row: int, col: int):
        self.win.move(row, col)

    def put(self, ch: int, highlight: bool=False):
        self.win.addch(ch, curses.A_REVERSE if highlight else curses.A_NORMAL)


@dataclass
class Glyph:
    c: str = ''
    row: int = 0
    col: int = 0
    width: int = 0


class Renderer:
    def __init__(
            self,
            doc: Document,
            scr: Screen,
            fname: str = '',
            guard_rows: int=3,
            preferred_row: int=0,
            tab: int=8,
        ):
        self.scr = scr
        self.doc = doc
        self.fname = fname  # for status line
        self.rows = self.scr.height - 1     # one for status
        self.cols = self.scr.width

        # layout options
        self.tab = tab
        assert (self.cols // self.tab) * self.tab == self.cols, "tab should divide cols"
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row or int(0.4*self.rows)
        self.preferred_col = 0
        self.preferred_top = self.doc.get_point() # top-left of screen
        self.is_column_sticky = True    # sticky col for vertical navigation

        self._bols: list[Location] = [] # cached beginning of line marks
        self.glyph = Glyph()
        self.wrap_lookahead: bool
        self.message = ''
        self.doc.watch(self.change_handler)

    def change_handler(self, start: Location, end: Location):
        self.bol_rescue(start)

    def clear_top(self):
        self.preferred_top = self.doc.get_end()

    def find_top(self):
        """
        Move the point to the top left of the screen,
        anchoring to preferred_top if possible.
        """
        if TYPE_CHECKING:
            # pylance doesn't know rows > preferred_row > 0
            k = 0
            fallback = self.doc.get_start()

        self.bol_ladder(self.rows // 2)

        self.clamp_to_bol()
        for k in range(1,self.rows+1):
            self.bol_to_prev_bol()
            if k == self.preferred_row:
                fallback = self.doc.get_point()
            if self.doc.get_point() == self.preferred_top:
                break

        # found top?
        if k < self.rows:
            # too close to point?
            while k < self.guard_rows:
                self.bol_to_prev_bol()
                k += 1

            # found top too far from point?
            while k >= self.rows - self.guard_rows:
                self.bol_to_next_bol()
                k -= 1
        else:
            self.doc.set_point(fallback)

        self.preferred_top = self.doc.get_point()

    def bol_iter_glyphs(self):
        pt = self.doc.get_point()
        if pt not in self._bols:
            self._bols = [pt]
            reset = ' (reset)'
        else:
            reset = ''
        logging.info(f'bol_iter_glyphs {len(self._bols)} {pt.position()}{reset}')
        self.glyph = Glyph()
        self.wrap_lookahead = True

    def get_next_glyph(self) -> Glyph:
        g = self.glyph
        g.c = self.doc.next_char()
        pt = self.doc.get_point()

        # update from previous glyph
        g.col += g.width
        if g.col >= self.cols:
            self.wrap_lookahead = True      # always safe at start of row
            g.col = 0
            g.row += 1

        if not g.c or g.c in ' -\t\n':
            self.wrap_lookahead = False
        elif not self.wrap_lookahead:
            # not-breaking character, need to do lookahead
            available = self.cols - g.col - 1
            while available:
                c = self.doc.next_char()
                if c in ' -\t\n':
                    break
                available -= 1
            if available:
                self.wrap_lookahead = True
            else:
                pt = pt.move(-1)    # unget the non-breaking character
                g.c = '\n'          # send a soft break instead
            self.doc.set_point(pt)

        match g.c:
            case '':
                g.width = 0
            case '\t':
                # Nb. assumes tab divides self.cols
                g.width = self.tab - (g.col % self.tab)
            case '\n':
                g.width = self.cols - g.col
            case _:
                g.width = 1

        if not g.c or g.width + g.col == self.cols:
            if pt not in self._bols:
                self._bols.append(pt)

        return g

    def show_status(self, msg: str, warn: bool=False):
        self.message = msg
        if warn:
            self.scr.alert()

    def status_line(self, cursor: tuple[int, int]) -> str:
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
                f"pcs {pt.chain_length()}/{self.doc.get_end().chain_length()}",
                f"eds {self.doc.edit_stack.sp}/{len(self.doc.edit_stack.edits)}",
            ])

        return " " + status + " " * (self.cols - len(status))

    def paint(self, mark: Location|None=None):
        """
        Paint the buffer to the screen, returning the new top-left location.
        Leaves point unchanged.
        """
        _n = self.doc.n_get_char_calls

        logging.info(f'paint top {len(self._bols)} bol')

        pt = self.doc.get_point()
        self.find_top()         # move point to show at top-left of screen

        _n = self.doc.n_get_char_calls - _n
        logging.info(f'paint glyphs {len(self._bols)} bol {_n} chars')

        self.scr.clear()        # move cursor to 0,0

        self.bol_iter_glyphs()
        cursor = (0, 0)

        highlight = mark is not None and mark < self.doc.get_point()

        while True:
            # if we're at the point, cursor appears on next glyph

            at_point = self.doc.get_point() == pt

            if self.doc.get_point() == mark:
                highlight = not highlight

            g = self.get_next_glyph()

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

        # update preferred column unless this was a non-sticky cursor movement
        if self.is_column_sticky:
            self.preferred_col = 0 if self.doc.at_end() else cursor[1]
        else:
            self.is_column_sticky = True

        status = self.status_line(cursor)
        try:
            # ignore the error when we advance past the end of the screen
            self.scr.move(self.rows, 0)
            self.scr.puts(status, highlight=True)
        except curses.error:
            pass

        self.scr.move(*cursor)
        self.scr.refresh()

        _n = self.doc.n_get_char_calls - _n
        logging.info(f'paint end {len(self._bols)} bol {_n} chars')


    ### Internal beginning-of-line routines

    def bol_ladder(self, height: int):
        """
        Ensure that the point is bracketed by BoL marks,
        with approximately height marks before the point.
        """
        pt = self.doc.get_point()
        if self._bols:
            # do we already bracket the point?
            if self._bols[0] < pt < self._bols[-1]:
                return

            # is the existing ladder still useful?
            if pt <= self._bols[0] or ((pt - self._bols[-1]) or 0) > height * self.cols:
                self._bols = []

        # find a reasonable starting point for the ladder
        if not self._bols:
            self.doc.move_point(-height * self.cols)
            self.doc.find_char_backward('\n')
            self._bols = [self.doc.get_point()]

        # extend the ladder until we bracket the point
        self.doc.set_point( self._bols[-1])
        while not self.doc.at_end() and self.doc.get_point() <= pt:
            self.bol_to_next_bol()

        self.doc.set_point(pt)

    def _bol_forward(self, max_col: int | None = None):
        """
        Advance point from BOL so that it appears at max_col
        (or earlier if the line is shorter).  If max_col is None
        we advance the point to the next BOL. i.e. so the cursor
        would appear at the start of the next line or at end of doc.
        """
        if max_col == 0:
            return

        if max_col is None:
            max_col = self.cols

        self.bol_iter_glyphs()
        while True:
            g = self.get_next_glyph()
            if g.width == 0 or g.row > 0 or g.col + g.width >= max_col:
                break

        # if we passed max_col we need to retreat one character
        if g.width + g.col > max_col:
            self.doc.move_point(-1)

    def bol_to_preferred_col(self):
        self._bol_forward(self.preferred_col)
        self.is_column_sticky = False

    def clamp_to_bol(self):
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        if self.doc.at_start() or self.doc.at_end():
            return

        pt = self.doc.get_point()
        if pt in self._bols:
            return

        if not self._bols or not (self._bols[0] <= pt < self._bols[-1]):
            self.bol_ladder(self.rows // 2)

        for (start, end) in zip(self._bols[-2::-1], self._bols[:0:-1]):
            if start <= pt < end:
                self.doc.set_point(start)
                return

        assert False, "clamp_to_bol failed"

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
        if self.doc.at_start():
            return

        # when there's a _bols cache miss on the way backward, we
        # end up discarding pre-calculated BOLs for the following lines.
        # we could do extra shenanigans to presereve the old list and tack it on
        # the end of the new one created by processing this line but the extra
        # complexity doesn't seem worth it: in normal use we pay the higher backward
        # cost once, and then the forward pass painting the screen primes the cache
        # and speeds up many subsequent frames unless the user is doing a lot of
        # long-range navigation.  Without a cache we process more than 6x
        # the characters on the screen while rendering it; once the cache is primed
        # that reduces to about 10-15% overhead

        try:
            i = self._bols.index(self.doc.get_point())
        except ValueError:
            self.bol_ladder(self.rows // 2)
            i = self._bols.index(self.doc.get_point())

        self.doc.set_point(self._bols[i-1])

    def bol_rescue(self, start: Location):
        """
        After most changes we can rescue most of the cached BoL marks.
        We need to recreate them based on position relative to the start
        of the document because the Location objects themselves might
        no longer be valid as when swapped out of the piece chain.
        We need to make sure to re-bracket the point, and don't
        bother if the movement was too large.
        """
        # anything to rescue?
        if not self._bols:
            return

        bols = self._bols
        self._bols = []
        last = bols.pop(0)
        # how far is the first BoL from the start of the change?
        pt = self.doc.get_point()
        delta = start.position() - last.position()

        # give up if start is before the first BoL or too far from point
        if delta < 0 or delta + (pt - start or 0) > self.cols * self.rows:
            return

        # reconstruct BoL up to the start of the change
        self._bols.append(start.move(-delta))
        for b in bols:
            d = (b - last)
            assert d is not None
            delta -= d
            if delta < 0:
                break
            self._bols.append(self._bols[-1].move(d))
            last = b

        logging.info(f'bol_rescue kept {len(self._bols)} bol')

        # re-bracket the point
        self.doc.set_point(self._bols[-1])
        while self._bols[-1] < pt:
            self.bol_to_next_bol()
        self.doc.set_point(pt)

        logging.info(f'bol_rescue bracketed point with {len(self._bols)} bol')
