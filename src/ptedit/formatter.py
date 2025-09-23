from collections import deque
import logging

from .location import Location
from .document import Document


hex_digits: list[int] = [ord(c) for c in '0123456789ABCDEF']


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

        self.bol_ladder = Ladder()      # cached beginning of line marks
        self.wrap_lookahead: bool

    def change_handler(self, start: Location, end: Location):
        self.rescue_ladder(start)

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
            # format and discard line to advance point
            self.format_line()

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

    def format_line(self) -> tuple[bytes, list[int]]:
        r"""
        Convert doc characters to a string of exactly 'cols' bytes that can
        be directly mapped to screen display characters.
        A column map is also returned which maps document offsets from BoL
        to corresponding screen columns.
        Normally a byte corresponds to a single document character,
        but there are a few exceptions:
        - 0x00 indicates a padding space, with no corresponding character in the document
        - 0x01 <x> is a control-escape for a single non-printable character c = 0x00-0x1f
          with x = c | 0x40, displayed as "^C" perhaps in a different color.
        - 0x02 <x> <y> is a hex-escape for a single non-printable character c > 0x7e
          with x,y as the hex nibbles, displayed as "\xy" perhaps in a different color.
        - whitespace bytes \t, \n and ' ' are normally be displayed as a single
          space (additional padding zero bytes will be added), but could be
          shown with a special character to indicate tabs or newlines.
        - the end-of-document is marked with a 0x00 byte.  This is indistinguishable
          from padding but is indexed in the column map for cursor placement.

        This representation makes it easy to compute the screen column
        given a document offset from BoL.
        """

        pt = self.doc.get_point()
        if pt not in self.bol_ladder:
            self.bol_ladder = Ladder([pt])
            logging.info(f'format_line reset to [{pt.position()}]')
        extend_ladder = pt == self.bol_ladder[-1]

        wrap_col = 0
        wrap_point: Location | None = None
        line = b''
        col_map: list[int] = []        # col_map[i] is column for document offset i
        done = False
        while len(line) < self.cols and not done:
            done = self.doc.at_end()        # treat eod as printable 0
            ch = ord(self.doc.next_char())
            if done or 32 <= ch < 127 or ch in (ord('\t'), ord('\n')):
                n = 0
            else:
                n = 1 if ch < 32 else 2
                if len(line) >= self.cols - n:
                    self.doc.move_point(-1)
                    break

            col_map.append(len(line))

            # unget the char if escaped version won't fit
            match n:
                case 0:
                    line += bytes([ch])
                    # wrappable?
                    if ch in (0, ord('\n'), ord('\t'), ord(' '), ord('-')):
                        wrap_col = len(line)
                        wrap_point = self.doc.get_point()
                        if ch == ord('\n'):
                            done = True         # 0 already handled by at_end test
                        elif ch == ord('\t'):
                            pad = (self.tab - len(line)) & (self.tab - 1)
                            line += bytes(pad)
                case 1:
                    # ctrl-escape, e.g. ^M
                    line += bytes([0x01, ch|0x40])
                case _:
                    # backslash-escape, e.g. \9E
                    line += bytes([0x02, hex_digits[ch // 16], hex_digits[ch%16]])

        if wrap_point:
            line = line[:wrap_col]
            col_map = [c for c in col_map if c < wrap_col]
            self.doc.set_point(wrap_point)

        pt = self.doc.get_point()
        if extend_ladder and pt != self.bol_ladder[-1]:
            self.bol_ladder.append(pt)

        line += bytes(self.cols - len(line))

        return line, col_map

    @staticmethod
    def offset_for_column(column: int, col_map: list[int]) -> int:
        if len(col_map) < 2:
            return 0
        offset = len(col_map) - 1
        while offset and col_map[offset] > column:
            offset -= 1
        return offset

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
