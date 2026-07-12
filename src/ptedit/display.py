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

    def find_top(self) -> bool:
        """Position the screen with a sticky top: keep last frame's top unless
        the cursor moved out of the visible window or into the guard zone,
        per docs/rendering.md. Sets bol_ladder.top and moves point there.
        Returns True if top changed (this frame's screen anchor differs from
        last frame's), False if it stayed the same.
        """
        stats.tick('find_top')
        stats.sample('find_top.ladder_len', float(len(self.layout.bol_ladder)))
        old_top_loc = self.top_loc
        cursor = self.doc.get_point()
        cur_idx = self.layout.ensure_bracketed(cursor)   # Phase 1: cursor is now in the ladder
        lad = self.layout.bol_ladder

        # Find last frame's top in the (possibly rebuilt) ladder.
        top_idx: int | None = None
        if self.top_loc is not None:
            top_idx = self.layout.line_index_of_loc(self.top_loc)

        if top_idx is not None and 0 <= cur_idx - top_idx < self.rows:
            # Cursor is on-screen relative to the sticky top.
            # Clamp the cursor's row-in-window into [guard_rows, rows - guard_rows - 1].
            delta = max(self.guard_rows, min(self.rows - self.guard_rows - 1, cur_idx - top_idx))
            top_idx = max(0, cur_idx - delta)
        else:
            # Cursor off-screen / no prior top / ladder rebuilt → recenter.
            stats.tick('find_top.recenter')
            self.layout.clamp_to_bol()
            for _ in range(self.preferred_row):
                if self.doc.at_start():
                    break
                self.layout.bol_to_prev_bol()
            recentered_top = self.doc.get_point()
            lad = self.layout.bol_ladder
            # After clamp_to_bol + bol_to_prev_bol the point is always a ladder
            # entry (each step follows the ladder or re-anchors around the new
            # position); the fallback never fires in practice.
            top_idx = self.layout.line_index(recentered_top)

        lad.top = top_idx
        self.top_loc = lad[top_idx]
        self.doc.set_point(lad[top_idx])
        return old_top_loc is None or old_top_loc != self.top_loc

    def _render_rows(
            self,
            start_row: int,
            end_row: int,
            mark: Location | None,
            top_idx: int,
            pt: Location,
    ) -> None:
        """Render ladder rows [start_row, end_row) to the screen.

        Extends the ladder as it formats each row (appending the next BoL when
        not already cached).
        """
        lad = self.layout.bol_ladder

        if start_row > 0:
            # Partial render (local-edit tail): position the cursor at the
            # first row we re-render; rows above are left as the last frame.
            self.scr.move(start_row, 0)

        # Ensure lad[top_idx + start_row] exists. For local_edit the row-K BoL
        # was truncated; format one line forward from the last surviving entry.
        while top_idx + start_row >= len(lad):
            self.doc.set_point(lad[-1])
            self.layout.format_line()
            if self.doc.at_end():
                break
            lad.append(self.doc.get_point())

        # Set the point at the first row we render, then format_line advances it.
        first_loc = lad[top_idx + start_row]
        self.doc.set_point(first_loc)
        start_pos = first_loc.position()

        pt_off = pt.position() - start_pos
        if mark:
            mark_off = mark.position() - start_pos
        else:
            mark_off = pt_off

        highlight = mark_off < 0

        row = start_row
        while row < end_row:
            line, col_map = self.layout.format_line()
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

            # format_line itself doesn't touch the ladder; we append the BoL it
            # advances to so subsequent rows / frames can index it.
            if not self.doc.at_end() and top_idx + row + 1 >= len(lad):
                lad.append(self.doc.get_point())

            row += 1

    def paint(self, mark: Location | None = None) -> Cell:
        """Paint the buffer to the screen; returns the cursor cell.
        Reads the document; the point is saved and restored."""
        pt = self.doc.get_point()

        edit_keep = self.layout.last_truncate_keep
        self.layout.last_truncate_keep = None
        top_invalidated = self.layout.last_truncate_invalidated_top
        self.layout.last_truncate_invalidated_top = False

        top_changed = self.find_top()
        top_idx = self.layout.bol_ladder.top

        row, col = self.layout.locate(pt)
        cursor = Cell(row - top_idx, col)
        assert 0 <= cursor.row < self.rows, "find_top must keep the cursor on screen"

        if top_changed or (edit_keep is not None and top_invalidated):
            stats.tick('paint.full')
            self.scr.clear()
            self._render_rows(0, self.rows, mark, top_idx, pt)
        elif edit_keep is not None:
            stats.tick('paint.local_edit')
            self._render_rows(edit_keep - top_idx, self.rows, mark, top_idx, pt)
        elif mark is not None and mark.position() != pt.position():
            stats.tick('paint.no_scroll_with_selection')
            self.scr.clear()
            self._render_rows(0, self.rows, mark, top_idx, pt)
        else:
            stats.tick('paint.no_scroll')

        self.doc.set_point(pt)
        return cursor
