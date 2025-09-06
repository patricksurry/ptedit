from dataclasses import dataclass
from collections import deque
import logging

from .location import Location
from .piecetable import Document


@dataclass
class Glyph:
    c: str = ''
    row: int = 0
    col: int = 0
    width: int = 0


class Ladder(deque[Location]):
    def __init__(self, locs: list[Location]=[]):
        super().__init__(locs, maxlen=48)

    def brackets(self, pt: Location):
        p, off = pt.tuple()
        assert len(self) > 0 and p.prev is not None
        start, end = self[0], self[-1]

        return (
            (start.is_strictly_before(pt) or (off == 0 and p.prev.prev is None and start == pt))
            and (pt.is_strictly_before(end) or (off == 0 and p.next is None and end == pt))
        )


class Formatter:
    def __init__(self, doc: Document, cols: int, rungs: int, tab: int=4):
        self.doc = doc

        assert (cols // tab) * tab == cols, "tab should divide cols"

        self.cols = cols
        self.rungs = rungs
        self.tab = tab

        self.preferred_col = 0
        self.is_column_sticky = True    # sticky col for vertical navigation

        self.bol_ladder = Ladder()      # cached beginning of line marks
        self.glyph = Glyph()
        self.wrap_lookahead: bool

    def change_handler(self, start: Location, end: Location):
        self.rescue_ladder(start)

    def set_preferred_col(self, col: int):
        # update preferred column unless this was a non-sticky cursor movement
        if self.is_column_sticky:
            # treat doc-end as BoL at col 0 even if missing trailing newline
            # otherwise backward-line gets stuck there
            self.preferred_col = 0 if self.doc.at_end() else col
        else:
            self.is_column_sticky = True

    def bol_to_preferred_col(self):
        """Snap back to preferred column, without changing it"""
        self._bol_forward(self.preferred_col)
        self.is_column_sticky = False

    def clamp_to_bol(self):
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        pt = self.doc.get_point()
        if self.doc.at_start() or self.doc.at_end() or pt in self.bol_ladder:
            return

        if not self.bol_ladder or not pt.within(self.bol_ladder[0],self.bol_ladder[-1]):
            self.ladder_point()

        # point is strictly bracketed, just find correct rung
        top = self.bol_ladder[0]
        assert pt.is_at_or_after(top)
        for bol in reversed(self.bol_ladder):  #TODO could skip first
            dbol, dpt = bol.distance_after(top), pt.distance_after(top)
            assert dbol is not None and dpt is not None
            if dbol <= dpt:
                self.doc.set_point(bol)
                return

        assert False, "clamp_to_bol failed"

    def bol_to_next_bol(self):
        bol = self.doc.get_point()

        n = len(self.bol_ladder)
        try:
            i = self.bol_ladder.index(bol)
        except:
            i = n     # force miss
        if i+1 < n:
            self.doc.set_point(self.bol_ladder[i+1])
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
            i = self.bol_ladder.index(self.doc.get_point())
        except ValueError:
            i = 0  # force miss

        if not i:
            self.ladder_point()
            i = len(self.bol_ladder) - (1 if self.doc.at_end() else 2)
            assert self.doc.get_point() == self.bol_ladder[i]

        self.doc.set_point(self.bol_ladder[i-1])

    ### Internal glyph rendering for BoL calcs and painting

    def iter_glyphs(self):
        pt = self.doc.get_point()
        if pt not in self.bol_ladder:
            self.bol_ladder = Ladder([pt])
            logging.info(f'iter_glyphs reset to [{pt.position()}]')
        self.wrap_lookahead = True
        return Glyph()

    def next_glyph(self, g: Glyph) -> Glyph:
        g.c = self.doc.next_char()
        pt = self.doc.get_point()

        # update from previous glyph
        g.col += g.width
        if g.col >= self.cols:
            self.wrap_lookahead = True      # always safe at start of row
            g.col = 0
            g.row += 1

        if g.c in ' -\t\n\0':
            self.wrap_lookahead = False
        elif not self.wrap_lookahead:
            # not-breaking character, need to do lookahead
            available = self.cols - g.col - 1
            while available:
                c = self.doc.next_char()
                if c in ' -\t\n\0':
                    break
                available -= 1
            if available:
                self.wrap_lookahead = True
            else:
                pt = pt.move(-1)    # unget the non-breaking character
                g.c = '\n'          # send a soft break instead
            self.doc.set_point(pt)

        match g.c:
            case '\0':
                g.width = 0
            case '\t':
                # Nb. assumes tab divides self.cols
                g.width = self.tab - (g.col % self.tab)
            case '\n':
                g.width = self.cols - g.col
            case _:
                g.width = 1

        if g.width == 0 or g.width + g.col == self.cols:
            if pt not in self.bol_ladder:
                self.bol_ladder.append(pt)

        return g

    ### Internal beginning-of-line routines

    def ladder_point(self):
        """
        Ensure that the point is strictly bracketed by BoL marks (or at start/end),
        with approximately 'rungs' marks before the point.
        """
        pt = self.doc.get_point()
        if self.bol_ladder:
            # do we already bracket the point?
            if self.bol_ladder.brackets(pt):
                return

            # is the existing ladder still useful?
            #TODO is this right
            if pt.is_at_or_before(self.bol_ladder[0]) or (pt.distance_after(self.bol_ladder[-1]) or 1e6) > self.rungs * self.cols:
                self.bol_ladder = Ladder()

        # find a reasonable starting point for the ladder
        if not self.bol_ladder:
            self.doc.move_point(-self.rungs * self.cols)
            self.doc.find_char_backward('\n')
            self.bol_ladder = Ladder([self.doc.get_point()])

        # extend the ladder until we bracket the point
        self.doc.set_point(self.bol_ladder[-1])
        while not self.doc.at_end() and self.doc.get_point().is_at_or_before(pt):
            self.bol_to_next_bol()

        self.doc.set_point(pt)

        assert self.bol_ladder.brackets(pt)

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

        g = self.iter_glyphs()
        while True:
            g = self.next_glyph(g)
            if g.width == 0 or g.row > 0 or g.col + g.width >= max_col:
                break

        # if we passed max_col we need to retreat one character
        if g.width + g.col > max_col:
            self.doc.move_point(-1)


    def rescue_ladder(self, start: Location):
        """
        After most changes we can rescue most of the cached BoL marks.
        We need to recreate them based on position relative to the start
        of the document because the Location objects themselves might
        no longer be valid as when swapped out of the piece chain.
        We need to make sure to re-bracket the point, and don't
        bother if the movement was too large.
        """
        # anything to rescue?
        if not self.bol_ladder:
            return

        bols = self.bol_ladder
        self.bol_ladder = Ladder()
        logging.info(f'rescue_ladder {len(self.bol_ladder)} bol, first/last/edit/pt {bols[0].position()}/{bols[-1].position()}/{start.position()}/{self.doc.get_point().position()}')

        # give up if start is before the first BoL or too far from point
        if (
            start.position() < bols[0].position() + self.cols
            or bols[-1].position() + self.cols * self.rungs < start.position()
        ):
            return

        # reconstruct BoL up to the start of the change
        # use position relative to start
        # how far is the first BoL from the start of the change?
        for i,b in enumerate(bols):
            logging.info(f"ladder {i}: {b} {b.position()}")
        prev = bols.popleft()
        delta = start.position() - prev.position()
        self.bol_ladder.append(start.move(-delta))
        for b in bols:
            d = b.distance_after(prev)
            if d is None:
                logging.info(f"{b} ancestors:")
                p = b.piece
                while p is not None:
                    p = p.prev
                    logging.info(p)
                logging.info(f"{prev} ancestors:")
                p = prev.piece
                while p is not None:
                    p = p.prev
                    logging.info(p)

            assert d is not None, f"failed! {b} - {prev} => {d}"
            delta -= d
            # change could affect line break position up to cols beforehand
            if delta < self.cols:
                break
            self.bol_ladder.append(self.bol_ladder[-1].move(d))
            prev = b

        logging.info(f'rescue_ladder kept {len(self.bol_ladder)} bol')
