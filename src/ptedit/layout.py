from __future__ import annotations
from collections.abc import Iterator

from .location import Location
from .document import Document
from .edit import Edit
from .stats import stats


hex_digits: list[int] = [ord(c) for c in '0123456789ABCDEF']


class Ladder(list[Location]):
    """BoL rungs for the visible region and its neighborhood, per docs/rendering.md.
    Python subclasses `list` (O(1) indexing); MAX is enforced on append by
    dropping the oldest rung. The `top` index lives with Display's frame
    state, not here."""
    MAX = 64

    def append(self, loc: Location) -> None:
        if len(self) == self.MAX:
            del self[0]
        super().append(loc)

    def reset(self, anchor: Location) -> None:
        """Discard everything; seed with a single anchor."""
        self.clear()
        super().append(anchor)


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
        self.damage_pos: int | None = None   # lowest doc position whose screen bytes may be stale

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

    def _move_vertical(self, forward: bool, count: int = 1) -> None:
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
            if forward:
                self.bol_to_next_bol()
            else:
                self.bol_to_prev_bol()
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
        self._move_vertical(forward=True)

    def move_backward_line(self) -> None:
        """Move cursor one visual line backward, tracking the goal column."""
        self._move_vertical(forward=False)

    def move_forward_page(self) -> None:
        """Move cursor `rows` visual lines forward."""
        self._move_vertical(forward=True, count=self.rows)

    def move_backward_page(self) -> None:
        """Move cursor `rows` visual lines backward."""
        self._move_vertical(forward=False, count=self.rows)

    def note_change(self, edit: Edit) -> None:
        """Record screen damage and repair the ladder through `edit`.

        Damage: any on-screen byte at or after `edit_pos - cols` may change
        (the cols margin covers soft-wrap pull-back, per docs/rendering.md).
        Ladder: remap entries through the edit; truncate at the first entry
        that fails either validity rule.
        """
        edit_pos = edit.get_change_start().position()
        dmg = max(0, edit_pos - self.cols)
        self.damage_pos = dmg if self.damage_pos is None else min(self.damage_pos, dmg)

        # A forward edit can move the point's document *position* while
        # leaving its (piece, offset) representation equal to a stale
        # last_vertical_dest (e.g. a coalesced backward-delete trims the
        # active edit's ins piece in place) — so the goal-column chain
        # can't survive an edit; any edit ends it, like invalidate() does.
        self.last_vertical_dest = None

        if not self.bol_ladder:
            return
        stats.sample('note_change.ladder_len_before', float(len(self.bol_ladder)))
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
        del self.bol_ladder[keep:]
        stats.sample('note_change.ladder_len_after', float(len(self.bol_ladder)))

    def invalidate(self) -> None:
        """Wholesale cache reset (undo/redo/squash): the next paint re-anchors."""
        self.bol_ladder.clear()
        self.damage_pos = None
        self.last_vertical_dest = None

    def take_damage(self) -> int | None:
        """Read and clear the damage watermark (once per frame)."""
        d = self.damage_pos
        self.damage_pos = None
        return d

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

    def bol(self, i: int) -> Location:
        """Read-only rung accessor for Display."""
        return self.bol_ladder[i]

    def ensure_row(self, i: int) -> Location:
        """Extend the ladder until entry `i` exists; return that BoL, or the
        end-of-document location if the document has fewer lines.
        Precondition: the ladder is non-empty (callers must reanchor first)."""
        lad = self.bol_ladder
        while i >= len(lad):
            self.doc.set_point(lad[-1])
            self.format_line()
            if self.doc.at_end():
                return self.doc.get_point()
            lad.append(self.doc.get_point())
        return lad[i]

    def render_lines(self, i: int, count: int) -> Iterator[tuple[bytes, list[int]]]:
        """Yield (line, col_map) for ladder rows [i, i+count), formatting
        forward and caching each newly reached BoL. Rows at/past the end of
        the document yield padding lines. The point flows forward; callers
        that need it preserved must save/restore."""
        self.doc.set_point(self.ensure_row(i))
        for k in range(count):
            line, col_map = self.format_line()
            if not self.doc.at_end() and i + k + 1 >= len(self.bol_ladder):
                self.bol_ladder.append(self.doc.get_point())
            yield line, col_map

    def make_room(self, top_idx: int, rows: int) -> int:
        """Evict leading rungs so rows [top_idx, top_idx+rows) can be appended
        without Ladder.append evicting mid-frame; returns the adjusted index.
        Assumes rows <= Ladder.MAX (a screen taller than the ladder capacity
        could never be fully bracketed)."""
        assert rows <= Ladder.MAX
        overflow = top_idx + rows - Ladder.MAX
        if overflow > 0:
            del self.bol_ladder[:overflow]
            top_idx -= overflow
        return top_idx

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

    def locate(self, cursor: Location) -> tuple[int, int]:
        """(ladder line index, screen column) for `cursor`; brackets it first."""
        i = self.ensure_bracketed(cursor)
        return i, self.column_at(self.bol_ladder[i], cursor)

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
