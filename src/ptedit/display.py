# The view layer: paints lines from Layout onto a Screen and tracks scroll state.
import logging

from .document import Document
from .location import Location
from .layout import Layout
from .screen import Screen


class Display:
    def __init__(
            self,
            doc: Document,
            scr: Screen,
            guard_rows: int=3,
            preferred_row: int=0,
            tab: int=4,
        ):
        self.scr = scr
        self.doc = doc
        self.rows = self.scr.height - 1     # one for status
        self.cols = self.scr.width

        self.layout = Layout(self.doc, self.cols, self.rows, self.rows // 2, tab)

        # layout options
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row if preferred_row else ((self.rows // 2) - 1)
        self.message = ''
        self.top_pos: int | None = None     # document position at screen row 0 last frame

        # Phase 2 redraw-strategy state
        self.prev_cursor: tuple[int, int] | None = None  # cursor cell from last frame

        self.doc.watch(self.change_handler)

    def change_handler(self, start: Location, end: Location, unlinked: frozenset | None = None):
        self.layout.change_handler(start, end, unlinked)

    ### External interface begins

    def recenter(self):
        """Force the cursor back toward the middle of the screen on next paint."""
        self.top_pos = None
        self.paint()

    def show_message(self, msg: str, warn: bool=False):
        self.message = msg
        if warn:
            self.scr.alert()
            logging.warning(msg)

    def find_top(self) -> bool:
        """Position the screen with a sticky top: keep last frame's top unless
        the cursor moved out of the visible window or into the guard zone,
        per docs/rendering.md. Sets bol_ladder.top and moves point there.
        Returns True if we recentered, False if we took the sticky path.
        """
        cursor = self.doc.get_point()
        self.layout.ensure_bracketed(cursor)        # Phase 1: cursor is now in the ladder
        lad = self.layout.bol_ladder
        cur_idx = self.layout.line_index(cursor)

        # Find last frame's top in the (possibly rebuilt) ladder.
        top_idx = None
        if self.top_pos is not None:
            for i, e in enumerate(lad):
                if e.position() == self.top_pos:
                    top_idx = i
                    break

        if top_idx is not None and 0 <= cur_idx - top_idx < self.rows:
            # cursor is on-screen relative to the sticky top — adjust for guard zone
            delta = cur_idx - top_idx
            if delta < self.guard_rows:
                top_idx = max(0, cur_idx - self.guard_rows)
            elif delta >= self.rows - self.guard_rows:
                top_idx = cur_idx - (self.rows - self.guard_rows - 1)
                if top_idx < 0:
                    top_idx = 0
            # else: no scroll, keep top_idx
            recentered = False
        else:
            # cursor off-screen / no prior top / ladder rebuilt → recenter
            self.layout.clamp_to_bol()
            for _ in range(self.preferred_row):
                if self.doc.at_start():
                    break
                self.layout.bol_to_prev_bol()
            recentered_top = self.doc.get_point()
            # After clamp_to_bol + bol_to_prev_bol the point is normally a
            # ladder entry already (each step follows the ladder or re-anchors
            # around the new position).  Fall back to reanchor only in the
            # degenerate case (single-entry ladder after reanchor inside
            # bol_to_prev_bol left the point off-ladder).
            lad = self.layout.bol_ladder
            if not any(e.position() == recentered_top.position() for e in lad):
                self.layout.reanchor(recentered_top)
                lad = self.layout.bol_ladder
            top_idx = self.layout.line_index(recentered_top)
            recentered = True

        lad.top = top_idx
        self.top_pos = lad[top_idx].position()
        self.doc.set_point(lad[top_idx])
        return recentered

    def _render_rows(
            self,
            start_row: int,
            end_row: int,
            mark: Location | None,
            at_end: bool,
            top_idx: int,
            original_pt: Location,
            emit: bool = True,
    ) -> tuple[tuple[int, int] | None, Location]:
        """Render ladder rows [start_row, end_row) to the screen.

        Extends the ladder as it formats each row (appending the next BoL when
        not already cached). Returns (cursor_cell, adjusted_pt) where cursor_cell is (row, col) if the
        cursor falls in [start_row, end_row), else None. adjusted_pt is original_pt
        possibly adjusted by the deferred pin_preferred_col column fixup.

        When emit=False, skips all scr.move/put calls — cursor and adjusted_pt
        are still computed (used by the no-scroll/no-selection fast path).
        Mutates self.layout.pin_preferred_col / preferred_col like the old paint did.
        """
        lad = self.layout.bol_ladder

        if emit and start_row > 0:
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

        pt_off = original_pt.position() - start_pos
        if mark:
            mark_off = mark.position() - start_pos
        else:
            mark_off = pt_off

        highlight = mark_off < 0

        cursor: tuple[int, int] | None = None
        adjusted_pt = original_pt

        row = start_row
        while row < end_row:
            line, col_map = self.layout.format_line()
            delta = len(col_map)
            toggle_mark = -1
            toggle_pt = -1

            if 0 <= pt_off < delta:
                # Deferred move to preferred column?
                if not at_end and self.layout.pin_preferred_col:
                    assert pt_off == 0, f"panic: pt_off={pt_off}"
                    pt_off = self.layout.offset_for_column(self.layout.preferred_col, col_map)
                    adjusted_pt = adjusted_pt.move(pt_off)
                    if not mark:
                        mark_off = pt_off
                col = col_map[pt_off]
                toggle_pt = col
                cursor = (row, col)

            if 0 <= mark_off < delta:
                # Found the mark?
                col = col_map[mark_off]
                toggle_mark = col

            pt_off -= delta
            mark_off -= delta

            if emit:
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

            # Cache the next row's BoL for future frames.
            if not self.doc.at_end() and top_idx + row + 1 >= len(lad):
                lad.append(self.doc.get_point())

            row += 1

        return cursor, adjusted_pt

    def _classify_paint_case(
            self,
            recentered: bool,
            edit_keep: int | None,
            top_invalidated: bool,
    ) -> str:
        """Map the four cases from docs/rendering.md Phase 2 table.

        recentered:      True if find_top recentered (top moved), False if sticky.
        edit_keep:       self.layout.last_truncate_keep consumed this frame (entries that
                         survived the last edit truncation), or None if no truncation.
        top_invalidated: True if the edit truncation reached or passed the old top row.
        Returns one of: 'full', 'local_edit', 'no_scroll'. (The doc's "scroll"
        case folds into 'full' here — both re-render the whole window in Python;
        only a real terminal block-copy would distinguish them.)
        """
        if recentered:
            return 'full'
        # Top unchanged.
        if edit_keep is not None:
            if top_invalidated:
                return 'full'
            return 'local_edit'
        return 'no_scroll'

    def paint(self, mark: Location|None=None) -> tuple[int, int]:
        """
        Paint the buffer content to the screen, returning the cursor position.
        Leaves point unchanged. The caller is responsible for the status line,
        restoring the cursor, and refreshing the screen.
        """
        original_pt = self.doc.get_point()
        at_end = self.doc.at_end()

        # Capture Phase 2 state before find_top changes things.
        edit_keep = self.layout.last_truncate_keep
        self.layout.last_truncate_keep = None
        top_invalidated = self.layout.last_truncate_invalidated_top
        self.layout.last_truncate_invalidated_top = False

        recentered = self.find_top()    # move point to show at top-left of screen

        lad = self.layout.bol_ladder
        top_idx = lad.top

        case = self._classify_paint_case(recentered, edit_keep, top_invalidated)

        if case == 'full':
            # Top changed (recenter / scroll / first paint): full redraw.
            self.scr.clear()
            cursor, adjusted_pt = self._render_rows(0, self.rows, mark, at_end, top_idx, original_pt)
            if cursor is None:
                cursor = (0, 0)     # shouldn't happen for a full render with point on screen

        elif case == 'local_edit':
            # Top unchanged, an edit truncated the ladder to edit_keep entries.
            # Rows [0, K) are byte-stable on screen; only [K, rows) need re-rendering.
            # Guaranteed 0 < K < rows here: if truncation reached top or above,
            # find_top would have recentered → classified 'full'.
            K = edit_keep - top_idx
            cursor, adjusted_pt = self._render_rows(K, self.rows, mark, at_end, top_idx, original_pt)
            if cursor is None:
                # Defensive: cursor is in an unchanged row [0, K) — recover from prev_cursor.
                cursor = self.prev_cursor or (0, 0)

        else:
            assert case == 'no_scroll'
            # Top unchanged, no edit. All rows are byte-stable.
            if mark is not None and mark.position() != original_pt.position():
                # Active selection: highlight region may have changed. For this Python
                # reference, fall back to full redraw. Cell-granular highlight delta
                # is a 6502 concern.
                self.scr.clear()
                cursor, adjusted_pt = self._render_rows(0, self.rows, mark, at_end, top_idx, original_pt)
                if cursor is None:
                    cursor = (0, 0)
            else:
                # Nothing on screen changed. Emit ZERO put calls.
                # Still compute the cursor cell so the terminal cursor can be placed.
                cursor_row = self.layout.line_index(original_pt) - top_idx
                if 0 <= cursor_row < self.rows:
                    cursor, adjusted_pt = self._render_rows(
                        cursor_row, cursor_row + 1, mark, at_end, top_idx, original_pt, emit=False,
                    )
                    if cursor is None:
                        cursor = self.prev_cursor or (cursor_row, 0)
                else:
                    # Shouldn't happen — find_top keeps cursor on screen — but recover.
                    cursor = self.prev_cursor or (0, 0)
                    adjusted_pt = original_pt
                    if self.layout.pin_preferred_col:
                        self.layout.pin_preferred_col = False

        self.doc.set_point(adjusted_pt)

        if not self.layout.pin_preferred_col:
            self.layout.preferred_col = cursor[1] if not self.doc.at_end() else 0
        else:
            self.layout.pin_preferred_col = False

        self.prev_cursor = cursor

        return cursor
