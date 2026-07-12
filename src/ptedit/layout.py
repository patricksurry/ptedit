from __future__ import annotations
import logging

from .location import Location
from .document import Document
from .edit import Edit
from .stats import stats


hex_digits: list[int] = [ord(c) for c in '0123456789ABCDEF']


class Ladder(list[Location]):
    """BoL marks for the visible region and its neighborhood, per docs/rendering.md.

    The doc specifies a 64-slot ring buffer with first/top/last indices —
    that's the Forth port's contract. In Python we subclass `list` directly:
    O(1) indexing (the hot path), with `MAX` enforced manually on `append`
    so the oldest entry is dropped on overflow. `top` is a plain int index
    into the live entries. A Forth port should re-derive the wrap-aware
    indexing from the spec.
    """
    MAX = 64

    def __init__(self) -> None:
        super().__init__()
        self.top: int = 0

    def append(self, loc: Location) -> None:
        if len(self) == self.MAX:
            del self[0]
            self.top = max(0, self.top - 1)
        super().append(loc)

    def truncate_to(self, count: int) -> None:
        """Keep the first `count` entries; discard the rest."""
        assert 0 <= count <= len(self)
        del self[count:]
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

        self.goal_col: int = 0                       # column vertical moves aim for
        self.last_vertical_dest: Location | None = None   # where the last vertical move landed

        self.bol_ladder = Ladder()
        self.last_truncate_keep: int | None = None  # entries kept after last edit truncation
        self.last_truncate_invalidated_top: bool = False  # True if truncation reached/passed top row

    # ----- cursor commands: layout-level vertical/line moves -----
    # `bol_to_next_bol` / `bol_to_prev_bol` are no-ops at doc end / start
    # respectively, so `_vertical_move` doesn't need its own boundary guards
    # around `step()` itself — it detects a no-op move (dest == bol) after
    # the fact and resets the goal column there instead.

    def move_start_line(self) -> None:
        """Move cursor to BoL of its current visual line."""
        self.clamp_to_bol()

    def move_end_line(self) -> None:
        """Move cursor to the end of its current visual line."""
        self.clamp_to_bol()
        self.bol_to_next_bol()
        if not self.doc.at_end():
            self.doc.move_point(-1)

    def _vertical_move(self, step, count: int = 1) -> None:
        """Apply `step` (bol_to_next_bol / bol_to_prev_bol) `count` times from
        the current line's BoL, landing on `goal_col` in the destination line.
        The goal column persists across consecutive vertical moves (traversing
        a short line doesn't lose the column) and is recomputed whenever the
        cursor moved in between."""
        cursor = self.doc.get_point()
        i = self.ensure_bracketed(cursor)
        bol = self.bol_ladder[i]
        if self.last_vertical_dest is None or cursor != self.last_vertical_dest:
            # Parity with the old renderer: a cursor at doc end targets col 0.
            self.goal_col = 0 if cursor.is_end() else self.column_at(bol, cursor)
        self.doc.set_point(bol)
        for _ in range(count):
            step()
        dest = self.doc.get_point()
        if dest != bol:
            _, col_map = self.format_line()      # formats the destination line
            self.doc.set_point(dest.move(self.offset_for_column(self.goal_col, col_map)))
        else:
            # Boundary: no line to move to; the old renderer reset the column here.
            self.goal_col = 0
        self.last_vertical_dest = self.doc.get_point()

    def move_forward_line(self) -> None:
        """Move cursor one visual line forward, tracking the goal column."""
        self._vertical_move(self.bol_to_next_bol)

    def move_backward_line(self) -> None:
        """Move cursor one visual line backward, tracking the goal column."""
        self._vertical_move(self.bol_to_prev_bol)

    def move_forward_page(self) -> None:
        """Move cursor `rows` visual lines forward."""
        self._vertical_move(self.bol_to_next_bol, self.rows)

    def move_backward_page(self) -> None:
        """Move cursor `rows` visual lines backward."""
        self._vertical_move(self.bol_to_prev_bol, self.rows)

    def change_handler(self, edit: Edit) -> None:
        """Truncate the ladder past entries invalidated by `edit`.

        See docs/rendering.md Validity / Remap for the two rules
        (remappable piece AND more than `cols` chars before edit start).
        """
        if not self.bol_ladder:
            return
        stats.sample('change_handler.ladder_len_before', float(len(self.bol_ladder)))
        edit_pos = edit.get_change_start().position()
        keep = 0
        for i, entry in enumerate(self.bol_ladder):
            new_loc = edit.remap_location(entry)
            if new_loc is None:
                break                                  # rule 1: piece can't be remapped
            if new_loc.position() + self.cols >= edit_pos:
                break                                  # rule 2: cols-margin guard
            if new_loc is not entry:
                self.bol_ladder[i] = new_loc           # in-place rewrite
            keep += 1
        original_len = len(self.bol_ladder)
        old_top = self.bol_ladder.top
        self.bol_ladder.truncate_to(keep)
        stats.sample('change_handler.ladder_len_after', float(len(self.bol_ladder)))
        if keep < original_len:
            self.last_truncate_keep = keep
            self.last_truncate_invalidated_top = (old_top >= keep)

    def reanchor(self, cursor: Location) -> None:
        """Rebuild the ladder fresh, rooted at the hard BoL at or before `cursor`."""
        stats.tick('reanchor')
        save_pt = self.doc.get_point()
        self.doc.set_point(cursor)
        # find_char_backward('\n') leaves point AFTER the newline (i.e. at
        # the hard BoL).  No move_point(-1) prelude is needed — calling
        # from a position that is already a hard BoL leaves point in place.
        if not self.doc.at_start():
            self.doc.find_char_backward('\n')
        anchor = self.doc.get_point()
        self.bol_ladder.reset(anchor)
        # Walk forward emitting visual lines until cursor is bracketed.
        while self.doc.get_point().is_strictly_before(cursor):
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
        self.bol_ladder.top = 0
        self.doc.set_point(save_pt)

    def _extend_to(self, cursor: Location) -> None:
        """Extend the ladder forward until `cursor` is bracketed."""
        save_pt = self.doc.get_point()
        self.doc.set_point(self.bol_ladder[-1])
        # Bound to `rows` iterations — anything further is more expensive
        # than a fresh redraw, so the caller should reanchor instead.
        added = 0
        while self.doc.get_point().is_strictly_before(cursor) and added < self.rows:
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
            added += 1
        self.doc.set_point(save_pt)

    def ensure_bracketed(self, cursor: Location) -> int:
        """Make sure the ladder brackets `cursor`, returning its line index.

        See docs/rendering.md Phase 1 for the bracket / extend / re-anchor
        cases.
        """
        lad = self.bol_ladder
        if not lad or cursor.is_strictly_before(lad[0]):
            stats.tick('ensure_bracketed.reanchor.before')
            self.reanchor(cursor)
        elif cursor.is_strictly_before(lad[-1]):
            stats.tick('ensure_bracketed.bracketed')
        else:
            gap = cursor.distance_after(lad[-1])
            if gap is None or gap > self.rows * self.cols:
                stats.tick('ensure_bracketed.reanchor.far')
                self.reanchor(cursor)
            else:
                stats.tick('ensure_bracketed.extend')
                self._extend_to(cursor)
        return self.line_index(cursor)

    def line_index(self, cursor: Location) -> int:
        """Index of the ladder entry whose visual line contains `cursor`."""
        lad = self.bol_ladder
        for i in range(len(lad) - 1):
            if cursor.is_strictly_before(lad[i + 1]):
                return i
        return len(lad) - 1

    def line_index_of_loc(self, loc: Location) -> int | None:
        """Index of the ladder entry equal to `loc`, or None if not found."""
        for i, entry in enumerate(self.bol_ladder):
            if entry == loc:
                return i
        return None

    def clamp_to_bol(self) -> None:
        """Move cursor to the BoL of its current visual line (no-op at doc start)."""
        if self.doc.at_start():
            return
        cursor = self.doc.get_point()
        i = self.ensure_bracketed(cursor)
        self.doc.set_point(self.bol_ladder[i])

    def bol_to_next_bol(self) -> None:
        """Move from a BoL to the next BoL (no-op at doc end)."""
        if self.doc.at_end():
            return
        bol = self.doc.get_point()
        i = self.ensure_bracketed(bol)
        if i + 1 < len(self.bol_ladder):
            self.doc.set_point(self.bol_ladder[i + 1])
            return
        # bol is the newest cached entry; format one more line to advance.
        self.format_line()
        if not self.doc.at_end():
            self.bol_ladder.append(self.doc.get_point())

    def bol_to_prev_bol(self) -> None:
        """Move from a BoL to the previous BoL (no-op at doc start)."""
        if self.doc.at_start():
            return
        bol = self.doc.get_point()
        i = self.ensure_bracketed(bol)
        if i > 0:
            self.doc.set_point(self.bol_ladder[i - 1])
            return
        # bol is the oldest cached entry — extend the ladder backward by
        # re-anchoring on the previous char and walking forward. After
        # reanchor, point is restored to that char; the prev visual BoL is
        # the ladder entry whose line contains it.  This works uniformly:
        # for a length-1 line above bol (empty paragraph OR a soft-wrap
        # artifact like 'abcd' / ' ' / 'efgh') line_index returns the index
        # of that length-1 line at cursor_arg; for a normal line it returns
        # the index of the line just before bol.
        stats.tick('bol_to_prev_bol.fallback')
        self.doc.move_point(-1)
        self.reanchor(self.doc.get_point())
        self.doc.set_point(self.bol_ladder[self.line_index(self.doc.get_point())])

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

    def column_at(self, bol: Location, cursor: Location) -> int:
        """Screen column of `cursor` within the visual line beginning at `bol`.
        Leaves the point unchanged."""
        off = cursor.distance_after(bol)
        assert off is not None, "column_at: cursor is not after bol"
        save = self.doc.get_point()
        self.doc.set_point(bol)
        _, col_map = self.format_line()
        self.doc.set_point(save)
        # off == len(col_map) shouldn't occur for a bracketed cursor; clamp defensively
        return col_map[min(off, len(col_map) - 1)] if col_map else 0

    @staticmethod
    def offset_for_column(column: int, col_map: list[int]) -> int:
        if len(col_map) < 2:
            return 0
        offset = len(col_map) - 1
        while offset and col_map[offset] > column:
            offset -= 1
        return offset
