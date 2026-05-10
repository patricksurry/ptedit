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

    def _reanchor(self, cursor: Location):
        """Rebuild the ladder fresh: backscan from cursor to nearest newline
        (or doc start), seed the ladder with that anchor, and forward-format
        until cursor is bracketed.

        find_char_backward('\n') leaves the point *after* the newline (i.e. at
        the hard BoL) if a newline is found, or at doc start otherwise.  No
        move_point(-1) prelude is needed: calling from a position that is
        already a hard BoL will land back at the same BoL, which is correct.
        """
        save_pt = self.doc.get_point()
        self.doc.set_point(cursor)
        if not self.doc.at_start():
            self.doc.find_char_backward('\n')
        anchor = self.doc.get_point()
        self.bol_ladder.reset(anchor)
        # Forward-format until the cursor lies within the cached range.
        while self.doc.get_point().is_strictly_before(cursor):
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
        # Top is the screen-anchor; for re-anchor, set it = first.
        self.bol_ladder.top = self.bol_ladder.first
        self.doc.set_point(save_pt)

    def _locate_cursor(self, cursor: Location) -> str:
        """Phase 1 step 2 from docs/rendering.md.
        Returns one of: 'bracketed', 'extend', 'reanchor'.
        """
        lad = self.bol_ladder
        if not lad:
            return 'reanchor'
        if cursor.is_strictly_before(lad[0]):
            return 'reanchor'
        if cursor.is_strictly_before(lad[-1]):
            return 'bracketed'
        # cursor is at or past the last entry
        gap = cursor.distance_after(lad[-1])
        if gap is None or gap > self.rows * self.cols:
            return 'reanchor'
        return 'extend'

    def _extend_to(self, cursor: Location):
        """Format forward from the last cached BoL until cursor is bracketed."""
        save_pt = self.doc.get_point()
        self.doc.set_point(self.bol_ladder[-1])
        added = 0
        while self.doc.get_point().is_strictly_before(cursor) and added <= self.rows:
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
            added += 1
        self.doc.set_point(save_pt)

    def _ensure_bracketed(self, cursor: Location | None = None):
        """Phase 1: ensure the ladder brackets `cursor` (defaults to point)."""
        if cursor is None:
            cursor = self.doc.get_point()
        match self._locate_cursor(cursor):
            case 'bracketed':
                return
            case 'extend':
                self._extend_to(cursor)
            case 'reanchor':
                self._reanchor(cursor)

    def _find_line_index(self, cursor: Location) -> int:
        """Index of the ladder entry whose line contains `cursor`."""
        lad = self.bol_ladder
        for i in range(len(lad) - 1):
            if cursor.is_strictly_before(lad[i + 1]):
                return i
        return len(lad) - 1

    def clamp_to_bol(self):
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        if self.doc.at_start():
            return
        cursor = self.doc.get_point()
        self._ensure_bracketed(cursor)
        i = self._find_line_index(cursor)
        self.doc.set_point(self.bol_ladder[i])

    def bol_to_next_bol(self):
        bol = self.doc.get_point()
        self._ensure_bracketed(bol)
        i = self._find_line_index(bol)
        if i + 1 < len(self.bol_ladder):
            self.doc.set_point(self.bol_ladder[i + 1])
            return
        # bol is the newest entry; format one more line to advance.
        self.format_line()
        if not self.doc.at_end():
            self.bol_ladder.append(self.doc.get_point())

    def bol_to_prev_bol(self):
        """
        Move from BOL to the previous BOL.
        This is a no-op at the document start.
        """
        if self.doc.at_start():
            return
        bol = self.doc.get_point()
        self._ensure_bracketed(bol)
        i = self._find_line_index(bol)
        if i > 0:
            self.doc.set_point(self.bol_ladder[i - 1])
            return
        # bol is the oldest entry — re-anchor before it.
        self.doc.move_point(-1)
        self._reanchor(self.doc.get_point())
        # Now bol must be the newest of a fresh ladder; new prev is at -2.
        if len(self.bol_ladder) >= 2:
            self.doc.set_point(self.bol_ladder[-2])

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
