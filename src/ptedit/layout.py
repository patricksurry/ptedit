from __future__ import annotations
import logging
from collections import deque
from typing import TYPE_CHECKING

from .location import Location
from .document import Document

if TYPE_CHECKING:
    from .piece import Piece


hex_digits: list[int] = [ord(c) for c in '0123456789ABCDEF']


class Ladder(deque):
    """BoL marks for the visible region and its neighborhood, per docs/rendering.md.

    The doc specifies a 64-slot ring buffer with first/top/last indices —
    that's the Forth port's contract. In Python we use a deque with a maxlen
    cap, which gives O(1) append-and-evict-oldest semantics; `top` is a plain
    int index into the live entries. A Forth port should re-derive the
    wrap-aware indexing from the spec.
    """
    MAX = 64

    def __init__(self) -> None:
        super().__init__(maxlen=self.MAX)
        self.top: int = 0

    def append(self, loc: Location) -> None:  # type: ignore[override]
        if len(self) == self.MAX:
            # Eviction will drop oldest; keep top valid relative to surviving entries.
            self.top = max(0, self.top - 1)
        super().append(loc)

    def truncate_to(self, count: int) -> None:
        """Keep the first `count` entries; discard the rest."""
        assert 0 <= count <= len(self)
        while len(self) > count:
            self.pop()
        if self.top >= count:
            self.top = max(0, count - 1)

    def reset(self, anchor: Location) -> None:
        """Discard everything; seed with a single anchor at top."""
        self.clear()
        super().append(anchor)
        self.top = 0


class Layout:
    def __init__(self, doc: Document, cols: int, rows: int, tab: int = 4) -> None:
        self.doc = doc

        assert (cols // tab) * tab == cols, "tab should divide cols"

        self.cols = cols
        self.rows = rows
        self.tab = tab

        self.preferred_col: int = 0         # last column that wasn't
        self.pin_preferred_col: bool = False  # True if cursor should track preferred col

        self.bol_ladder = Ladder()
        self.last_truncate_keep: int | None = None  # entries kept after last edit truncation
        self.last_truncate_invalidated_top: bool = False  # True if truncation reached/passed top row

    # ----- line moves: layout-level operations on the ladder/cursor -----

    def move_start_line(self) -> None:
        self.clamp_to_bol()

    def move_end_line(self) -> None:
        self.clamp_to_bol()
        self.bol_to_next_bol()
        if not self.doc.at_end():
            self.doc.move_point(-1)

    def move_forward_line(self) -> None:
        self.clamp_to_bol()
        if not self.doc.at_end():
            self.bol_to_next_bol()
            # defer column setting until we render the line with the point
            self.pin_preferred_col = True

    def move_backward_line(self) -> None:
        self.clamp_to_bol()
        if not self.doc.at_start():
            self.bol_to_prev_bol()
            self.pin_preferred_col = True

    def move_forward_page(self) -> None:
        self.clamp_to_bol()
        for _ in range(self.rows):
            self.bol_to_next_bol()
        self.pin_preferred_col = True

    def move_backward_page(self) -> None:
        self.clamp_to_bol()
        for _ in range(self.rows):
            self.bol_to_prev_bol()
        self.pin_preferred_col = True

    def change_handler(
            self,
            start: Location,
            end: Location,
            unlinked: tuple['Piece', 'Piece'] | None = None,
    ) -> None:
        """Truncate the ladder at the first invalid entry per docs/rendering.md."""
        if not self.bol_ladder:
            return
        edit_pos = start.position()
        # Build a small id-set for fast membership; chain length is typically 1-3.
        unlinked_ids: set[int] = set()
        if unlinked is not None:
            first, last = unlinked
            p: Piece | None = first
            while p is not None:
                unlinked_ids.add(id(p))
                if p is last:
                    break
                p = p.next
        keep = 0
        for entry in self.bol_ladder:
            piece, _offset = entry.tuple()
            # Validity rule 1: piece id not in unlinked set (ids of removed pieces).
            if id(piece) in unlinked_ids:
                break
            # Validity rule 2: entry more than `cols` chars before edit.
            if entry.position() + self.cols >= edit_pos:
                break
            keep += 1
        original_len = len(self.bol_ladder)
        old_top = self.bol_ladder.top
        self.bol_ladder.truncate_to(keep)
        # Record the truncation count only when entries were actually dropped.
        if keep < original_len:
            self.last_truncate_keep = keep
            self.last_truncate_invalidated_top = (old_top >= keep)

    def reanchor(self, cursor: Location) -> None:
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
        # Top is the screen-anchor; for re-anchor, set it = 0 (the spec's "first").
        # reset() already did this, kept for clarity vs the spec's first/top/last.
        self.bol_ladder.top = 0
        self.doc.set_point(save_pt)

    def _extend_to(self, cursor: Location) -> None:
        """Format forward from the last cached BoL until cursor is bracketed."""
        save_pt = self.doc.get_point()
        self.doc.set_point(self.bol_ladder[-1])
        added = 0
        while self.doc.get_point().is_strictly_before(cursor) and added < self.rows:
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
            added += 1
        self.doc.set_point(save_pt)

    def ensure_bracketed(self, cursor: Location) -> int:
        """Phase 1: ensure the ladder brackets `cursor`.

        Extends the ladder forward when the cursor is close past the last
        entry, re-anchors otherwise (cursor before the ladder, or far past
        the end). Returns the cursor's line index in the (possibly extended)
        ladder."""
        lad = self.bol_ladder
        if not lad or cursor.is_strictly_before(lad[0]):
            self.reanchor(cursor)
        elif cursor.is_strictly_before(lad[-1]):
            pass  # already bracketed
        else:
            gap = cursor.distance_after(lad[-1])
            if gap is None or gap > self.rows * self.cols:
                self.reanchor(cursor)
            else:
                self._extend_to(cursor)
        return self.line_index(cursor)

    def line_index(self, cursor: Location) -> int:
        """Index of the ladder entry whose line contains `cursor`."""
        lad = self.bol_ladder
        for i in range(len(lad) - 1):
            if cursor.is_strictly_before(lad[i + 1]):
                return i
        return len(lad) - 1

    def line_index_of_loc(self, loc: Location) -> int | None:
        """Return the index of the ladder entry equal to `loc`, or None if not found."""
        for i, entry in enumerate(self.bol_ladder):
            if entry == loc:
                return i
        return None

    def clamp_to_bol(self) -> None:
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        if self.doc.at_start():
            return
        cursor = self.doc.get_point()
        i = self.ensure_bracketed(cursor)
        self.doc.set_point(self.bol_ladder[i])

    def bol_to_next_bol(self) -> None:
        """Move from a BoL to the next BoL. Precondition: point is on a BoL.

        Uses the ladder when the next BoL is cached; otherwise formats one
        line forward and appends it.
        """
        bol = self.doc.get_point()
        i = self.ensure_bracketed(bol)
        if i + 1 < len(self.bol_ladder):
            self.doc.set_point(self.bol_ladder[i + 1])
            return
        # bol is the newest entry; format one more line to advance.
        self.format_line()
        if not self.doc.at_end():
            self.bol_ladder.append(self.doc.get_point())

    def bol_to_prev_bol(self) -> None:
        """Move from a BoL to the previous BoL.

        No-op at document start. Uses the ladder when the previous BoL is
        cached; otherwise re-anchors on the line above and steps back.
        """
        if self.doc.at_start():
            return
        bol = self.doc.get_point()
        i = self.ensure_bracketed(bol)
        if i > 0:
            self.doc.set_point(self.bol_ladder[i - 1])
            return
        # bol is the oldest entry — re-anchor on the line before it, then take
        # the BoL just before bol (ladder[-2]). If that re-anchor produced only
        # a single entry, it's bol-1 itself (an empty line just above bol) and
        # reanchor already left the point there — nothing more to do.
        self.doc.move_point(-1)
        self.reanchor(self.doc.get_point())
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
