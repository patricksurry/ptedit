# The view layer: paints lines from Layout onto a Screen and tracks scroll state.
from __future__ import annotations
import logging
from typing import NamedTuple

from .document import Document
from .edit import Edit
from .location import Location
from .layout import Layout
from .screen import Screen
from .stats import stats


class Cell(NamedTuple):
    row: int
    col: int


class Display:
    def __init__(
            self,
            doc: Document,
            scr: Screen,
            guard_rows: int = 3,
            preferred_row: int = 0,
            tab: int = 4,
    ) -> None:
        self.scr = scr
        self.doc = doc
        self.rows = self.scr.height - 1     # one for status
        self.cols = self.scr.width

        self.layout = Layout(self.doc, self.cols, self.rows, tab)

        # layout options
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row if preferred_row else ((self.rows // 2) - 1)
        self.message = ''
        self.top_loc: Location | None = None     # ladder entry shown at screen row 0 last frame
        self.prev_selection: bool = False        # True if last frame painted a selection highlight

        self.doc.watch(self.change_handler)

    def change_handler(self, edit: Edit) -> None:
        self.layout.change_handler(edit)
        # Keep top_loc in sync with any in-place ladder remaps: if top_loc's
        # piece was the unlinked piece, remap it so find_top can still locate
        # it in the updated ladder.  If it can't be remapped (deleted middle or
        # multi-piece unlink), clear it to force a recenter next frame.
        if self.top_loc is not None:
            self.top_loc = edit.remap_location(self.top_loc)

    ### External interface begins

    def recenter(self) -> None:
        """Force the next paint to recenter the cursor."""
        self.top_loc = None

    def show_message(self, msg: str, warn: bool = False) -> None:
        self.message = msg
        if warn:
            self.scr.alert()
            logging.warning(msg)

    def find_top(self) -> tuple[int, bool]:
        """Choose the screen-row-0 rung with a sticky top per docs/rendering.md.
        Returns (top index, whether the top changed since last frame)."""
        stats.tick('find_top')
        stats.sample('find_top.ladder_len', float(len(self.layout.bol_ladder)))
        old_top_loc = self.top_loc
        cursor = self.doc.get_point()
        cur_idx = self.layout.ensure_bracketed(cursor)

        top_idx: int | None = None
        if self.top_loc is not None:
            top_idx = self.layout.line_index_of_loc(self.top_loc)

        if top_idx is not None and 0 <= cur_idx - top_idx < self.rows:
            # Sticky: clamp the cursor's row into [guard_rows, rows - guard_rows - 1].
            delta = max(self.guard_rows, min(self.rows - self.guard_rows - 1, cur_idx - top_idx))
            top_idx = max(0, cur_idx - delta)
        else:
            stats.tick('find_top.recenter')
            self.layout.clamp_to_bol()
            for _ in range(self.preferred_row):
                if self.doc.at_start():
                    break
                self.layout.bol_to_prev_bol()
            top_idx = self.layout.line_index(self.doc.get_point())

        top_idx = self.layout.make_room(top_idx, self.rows)
        self.top_loc = self.layout.bol(top_idx)
        return top_idx, (old_top_loc is None or old_top_loc != self.top_loc)

    def _render_rows(
            self,
            start_row: int,
            end_row: int,
            mark: Location | None,
            top_idx: int,
            pt: Location,
    ) -> None:
        """Emit ladder rows [start_row, end_row) to the screen, highlighting
        the [mark, pt) selection. Rows above start_row are assumed byte-stable
        in the video buffer."""
        if start_row > 0:
            self.scr.move(start_row, 0)

        start_pos = self.layout.ensure_row(top_idx + start_row).position()
        pt_off = pt.position() - start_pos
        mark_off = mark.position() - start_pos if mark else pt_off
        highlight = mark_off < 0

        for line, col_map in self.layout.render_lines(top_idx + start_row, end_row - start_row):
            delta = len(col_map)
            toggle_pt = col_map[pt_off] if 0 <= pt_off < delta else -1
            toggle_mark = col_map[mark_off] if 0 <= mark_off < delta else -1
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

    def _first_dirty_row(self, damage_pos: int, top_idx: int) -> int:
        """First screen row whose bytes may differ from the video buffer, given
        document content at/after `damage_pos` may have changed. Row r is clean
        iff its line ends at or before damage_pos (i.e. the next BoL's position
        is <= damage_pos). Returns rows when the damage is entirely below the
        window (possible when an edit truncated rungs kept past the screen)."""
        dirty = 0
        for r in range(self.rows):
            i = top_idx + r + 1
            if i >= len(self.layout.bol_ladder):
                break                       # no cached rung below: damage row stands
            if self.layout.bol(i).position() <= damage_pos:
                dirty = r + 1
            else:
                break
        return dirty

    def paint(self, mark: Location | None = None) -> Cell:
        """Paint the buffer to the screen; returns the cursor cell.
        Reads the document; the point is saved and restored."""
        pt = self.doc.get_point()

        damage_pos = self.layout.take_damage()
        selection = mark is not None and mark.position() != pt.position()

        top_idx, top_changed = self.find_top()

        row, col = self.layout.locate(pt)
        cursor = Cell(row - top_idx, col)
        assert 0 <= cursor.row < self.rows, "find_top must keep the cursor on screen"

        if top_changed or selection or self.prev_selection:
            first_dirty = 0
        elif damage_pos is not None:
            first_dirty = self._first_dirty_row(damage_pos, top_idx)
        else:
            first_dirty = self.rows

        if first_dirty == 0:
            stats.tick('paint.full')
            self.scr.clear()
            self._render_rows(0, self.rows, mark, top_idx, pt)
        elif first_dirty < self.rows:
            stats.tick('paint.local_edit')
            self._render_rows(first_dirty, self.rows, mark, top_idx, pt)
        else:
            stats.tick('paint.no_scroll')

        self.prev_selection = selection
        self.doc.set_point(pt)
        return cursor
