import logging

from .location import Location
from .document import Document


hex_digits: list[int] = [ord(c) for c in '0123456789ABCDEF']


class Ladder:
    """
    Sequence of BoL Locations covering the visible region and its
    immediate neighborhood, per docs/rendering.md.

    The doc describes a 64-slot ring buffer with three indices
    (first/top/last) — that's the contract for the 6502/Forth port,
    where the byte budget matters. This Python reference uses a plain
    list for clarity:

        first == 0           (always; we trim from the front)
        last  == len(slots)  (always)
        top                  is a simple integer index in [first, last)

    The algorithm in the doc is unchanged; only the data structure
    differs. A Forth port should re-derive the wrap-aware index math
    from the spec.
    """
    MAX = 64

    def __init__(self):
        self.slots: list[Location] = []
        self.top: int = 0

    @property
    def first(self) -> int:
        return 0

    @property
    def last(self) -> int:
        return len(self.slots)

    def __bool__(self) -> bool:
        return bool(self.slots)

    def __len__(self) -> int:
        return len(self.slots)

    def __iter__(self):
        return iter(self.slots)

    def __getitem__(self, i: int) -> Location:
        return self.slots[i]

    def append(self, loc: Location):
        self.slots.append(loc)
        if len(self.slots) > self.MAX:
            self.slots.pop(0)
            self.top = max(0, self.top - 1)

    def truncate_to(self, count: int):
        """Keep the first `count` entries; discard the rest."""
        assert 0 <= count <= len(self.slots)
        del self.slots[count:]
        if self.top >= count:
            self.top = max(0, count - 1)

    def reset(self, anchor: Location):
        """Discard everything; seed with a single anchor at top."""
        self.slots = [anchor]
        self.top = 0


class Layout:
    def __init__(self, doc: Document, cols: int, rows: int, rungs: int, tab: int=4):
        self.doc = doc

        assert (cols // tab) * tab == cols, "tab should divide cols"

        self.cols = cols
        self.rows = rows
        self.rungs = rungs
        self.tab = tab

        self.preferred_col = 0          # last column that wasn't
        self.pin_preferred_col = False  # True if cursor should track preferred col

        self.bol_ladder = Ladder()

    # ----- line moves (absorbed from Display) -----

    def move_start_line(self):
        self.clamp_to_bol()

    def move_end_line(self):
        self.clamp_to_bol()
        self.bol_to_next_bol()
        if not self.doc.at_end():
            self.doc.move_point(-1)

    def move_forward_line(self):
        self.clamp_to_bol()
        if not self.doc.at_end():
            self.bol_to_next_bol()
            # defer column setting until we render the line with the point
            self.pin_preferred_col = True

    def move_backward_line(self):
        self.clamp_to_bol()
        if not self.doc.at_start():
            self.bol_to_prev_bol()
            self.pin_preferred_col = True

    def move_forward_page(self):
        self.clamp_to_bol()
        for _ in range(self.rows):
            self.bol_to_next_bol()
        self.pin_preferred_col = True

    def move_backward_page(self):
        self.clamp_to_bol()
        for _ in range(self.rows):
            self.bol_to_prev_bol()
        self.pin_preferred_col = True

    def change_handler(self, start: Location, end: Location, unlinked: frozenset | None = None):
        """Truncate the ladder at the first invalid entry per docs/rendering.md."""
        if not self.bol_ladder:
            return
        edit_pos = start.position()
        keep = 0
        for entry in self.bol_ladder:
            piece, _offset = entry.tuple()
            # Validity rule 1: piece id not in unlinked set (ids of removed pieces).
            if unlinked is not None and id(piece) in unlinked:
                break
            # Validity rule 2: entry more than `cols` chars before edit.
            if entry.position() + self.cols >= edit_pos:
                break
            keep += 1
        self.bol_ladder.truncate_to(keep)

    def clamp_to_bol(self):
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        if self.doc.at_start():
            return

        pt = self.doc.get_point()

        # Backscan to the hard BoL (character after the preceding \n, or doc start)
        self.doc.find_char_backward('\n')
        # find_char_backward leaves us *after* the \n if found, or at doc start

        # Forward-walk visual lines until we reach or pass pt
        while self.doc.get_point().is_strictly_before(pt):
            prev_bol = self.doc.get_point()
            self.format_line()
            if pt.is_strictly_before(self.doc.get_point()):
                # Next BoL strictly passed pt; the last BoL before pt is prev_bol
                self.doc.set_point(prev_bol)
                return

        # The point is either exactly at pt (pt is a BoL) or we started at/after pt
        # (pt was already at hard_bol); leave the point where the walk landed.
        pass

    def bol_to_next_bol(self):
        # format and discard line to advance point
        self.format_line()

    def bol_to_prev_bol(self):
        """
        Move from BOL to the previous BOL.
        This is a no-op at the document start.
        """
        if self.doc.at_start():
            return

        pt = self.doc.get_point()

        # Step back one character to get before the current BoL, then backscan
        self.doc.move_point(-1)
        self.doc.find_char_backward('\n')
        # find_char_backward leaves us *after* the \n if found, or at doc start
        hard_bol = self.doc.get_point()

        # Forward-walk visual lines to find the BoL immediately before pt.
        # We track prev_bol so that when format_line() reaches or passes pt,
        # prev_bol holds the last BoL that was strictly before pt.
        prev_bol = hard_bol
        while self.doc.get_point().is_strictly_before(pt):
            prev_bol = self.doc.get_point()
            self.format_line()

        # Loop exits when next BoL is at-or-after pt; prev_bol is the previous BoL
        self.doc.set_point(prev_bol)

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
                # unget the char if escaped version won't fit
                if len(line) >= self.cols - n:
                    self.doc.move_point(-1)
                    break

            col_map.append(len(line))

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
