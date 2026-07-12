# Rendering/MVC Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each layer of the editor one clearly stated responsibility so the
rendering pipeline can be reasoned about (and later ported to 6502) invariant by
invariant, without changing visible behavior.

**Architecture:** Five invariants drive every task (see *Design* below): commands
complete themselves; paint never writes the model; Layout is the ladder's only
owner; screen damage is a single document position; incremental cache repair only
on the typing hot path — undo/redo/squash invalidate wholesale.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Branch: `rendering-redesign`
(continues the existing PR).

## Global Constraints

- Behavior-preserving refactor: `uv run pytest` green after every task; golden
  render tests byte-identical (the one intentional visual change — the
  stale-highlight bug fix in Task 3 — gets its own red test first).
- Perf gate: the four perftest scenarios must stay within ~10% of the baseline
  captured at `e7dae25` (this machine): insert **369** / up_from_end **1434** /
  pgup_from_end **258** / pgdn_from_top **348** fps. Command:
  `for s in insert up_from_end pgup_from_end pgdn_from_top; do uv run python -m ptedit -P $s tests/alice1flow.asc; done`
- Undo/redo/squash are explicitly exempt from the perf gate (design decision:
  simplicity over speed on rarely-used paths).
- 6502 scrutability: no new dynamic data structures; prefer plain ints
  (document positions, row indices) over object graphs for cross-layer state.
- Commit style matches repo history (`refactor:`, `fix:`, `test:`, `docs(...)`).

---

## Design

### The problem being fixed

Today the layers leak into each other in four specific ways:

1. **Paint completes cursor commands.** `move_backward_line` parks the point at
   a BoL, sets `pin_preferred_col`, and the *next* `Display.paint` computes the
   real column and moves the point (`adjusted_pt`). The view writes the model.
2. **Damage signalling is two frame-scoped flags** (`last_truncate_keep`,
   `last_truncate_invalidated_top`) captured-and-cleared by paint, feeding a
   four-way branch. The flags are ladder *indices*, which silently go stale if
   the ladder is rebuilt or evicts between edit and paint.
3. **Three writers mutate `bol_ladder`** (Layout methods, `find_top`,
   `_render_rows`), and `Ladder.top` duplicates `Display.top_loc`.
4. **The observer list hides ordering.** Four watchers with registration-order
   dependencies; undo notifies with the *previous* edit, so incremental remap
   is only correct for the apply direction (it currently survives by a subtle
   chain of accidents — verified empirically, but undocumented).

Plus one live bug found during review: clearing the mark on a stable window
leaves the old selection highlight on screen (the `no_scroll` path emits zero
cells and nothing records that the previous frame was highlighted).

### Target invariants

| # | Invariant | Enforced by |
|---|-----------|-------------|
| 1 | A command leaves the point where the user sees it; nothing later "fixes it up". | Task 1 |
| 2 | `paint()` reads the document, saves/restores the point, and never mutates model or Layout movement state. | Tasks 1–3 |
| 3 | `bol_ladder` is written only inside `Layout`. Display consumes it through `locate`, `bol`, `ensure_row`, `render_lines`, `make_room`. | Task 4 |
| 4 | Screen damage is one number: the lowest **document position** whose on-screen bytes may be stale (`damage_pos`). Positions survive ladder rebuilds/evictions; indices don't. | Task 3 |
| 5 | Incremental cache repair (remap + truncate) happens only for insert/delete/replace. Undo, redo, and squash reset all caches. One change hook (`Document.on_change`), one consumer (`Display`). | Task 5 |

### How a frame works after the cleanup

```
paint(mark):
  pt          = point (saved; restored at the end)
  damage_pos  = layout.take_damage()            # int | None, set by edits
  selection   = mark active and != pt
  top_idx, top_changed = find_top()             # sticky top, unchanged logic
  cursor      = locate(pt)                      # (row, col) — pure lookup
  first_dirty = 0            if top_changed or selection or prev_selection
              = row_of(damage_pos)  if damage_pos       # watermark
              = rows         otherwise                  # emit nothing
  render rows [first_dirty, rows)
```

The 6502 port maps this directly: `damage_pos` is a 16-bit document position
(rungs already store `pos` per `docs/rendering.md`), `first_dirty` is one byte,
and the render loop is the existing Phase-2 row loop starting at a computed row.

### Non-goals (explicitly out of scope)

- The `'abcd'/' '/'efgh'` soft-wrap wart in `format_line` (separate concern,
  noted in rendering.md).
- Video-RAM block-move scroll optimization (Forth port concern).
- Collapsing the keymap to a single command namespace (bindings to
  `ed`/`layout`/`dpy` are honest about where each command lives).
- Removing the `goal_col = 0` at-doc-end parity guard (listed as a follow-up).

### File map

| File | Change |
|------|--------|
| `src/ptedit/layout.py` | eager `_vertical_move` + `goal_col`; `column_at`/`locate`; `damage_pos`; `ensure_row`/`render_lines`/`make_room`/`bol`; `invalidate`; `Ladder` loses `top`/`truncate_to` |
| `src/ptedit/display.py` | paint becomes read-only single-flow; `find_top` returns `(top_idx, changed)`; `note_change(edit | None)`; `prev_selection`; loses `prev_cursor`, `emit=False`, `adjusted_pt` |
| `src/ptedit/document.py` | single `on_change` hook; `_notify(edit | None)`; undo/redo/squash notify `None` |
| `src/ptedit/editor.py` | drops watcher & isearch mode-branching; explicit `mark = None` in undo/redo/squash |
| `src/ptedit/controller.py` | drops watcher; autosave driven from the key loop; `_act` routes bare ints per mode |
| `src/ptedit/piece.py` | `eq=False` on all `Piece` dataclasses (identity equality) |
| `tests/` | new unit tests per task; fixture updates for the `on_change` hook |
| `docs/rendering.md`, `docs/plans/perf-baseline.md`, `README.md` | updated to match |

---

### Task 1: Eager vertical movement — goal column owned by Layout

**Files:**
- Modify: `src/ptedit/layout.py:59-109` (state + `_vertical_move`)
- Modify: `src/ptedit/display.py` (delete pin-fixup machinery from `_render_rows`/`paint`)
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: existing `Layout.ensure_bracketed`, `format_line`, `offset_for_column`.
- Produces: `Layout.column_at(bol: Location, cursor: Location) -> int` (screen
  column of cursor within the visual line starting at `bol`; leaves point
  unchanged). `Layout.goal_col: int` and `Layout.last_vertical_dest: Location | None`
  replace `preferred_col`/`pin_preferred_col` (Task 5's `invalidate()` resets
  `last_vertical_dest`). `Display._render_rows` signature becomes
  `(start_row, end_row, mark, top_idx, pt)` returning `Cell | None` (cursor cell
  only, no `adjusted_pt`; Task 2 drops the return entirely).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_layout.py`:

```python
def test_goal_column_persists_across_short_line():
    """Vertical moves land on the goal column immediately (no paint needed)."""
    doc = document.Document('abcdefgh\nab\nabcdefgh\n')
    lay = layout.Layout(doc, cols=16, rows=8)
    doc.move_point(5)                           # line 0, col 5
    lay.move_forward_line()
    assert doc.get_point().position() == 11     # 'ab' line clamps to its newline (col 2)
    lay.move_forward_line()
    assert doc.get_point().position() == 17     # long line again: goal col 5 restored


def test_vertical_move_at_start_clamps_to_bol():
    doc = document.Document('abcdefgh\nab\n')
    lay = layout.Layout(doc, cols=16, rows=8)
    doc.move_point(5)
    lay.move_backward_line()                    # no line above: clamp to BoL
    assert doc.get_point().position() == 0


def test_vertical_move_from_doc_end_without_trailing_newline():
    """Parity guard: a cursor at doc end targets column 0 (old renderer rule).

    Without a trailing newline, reanchor's walk appends a ladder rung exactly
    at doc end, so the EOD cursor brackets to its own pseudo-line and one
    bol_to_prev_bol lands on the last real line's BoL (verified against the
    pre-refactor pipeline)."""
    doc = document.Document('abcdefgh\nabcd')
    lay = layout.Layout(doc, cols=16, rows=8)
    doc.set_point_end()                         # EOD marker at col 4 of line 1
    lay.move_backward_line()
    assert doc.get_point().position() == 9      # BoL of the 'abcd' line
```

(Match the file's existing import style — it already imports `document` and
`layout`.)

- [ ] **Step 2: Run tests to verify the first fails**

Run: `uv run pytest tests/test_layout.py -k goal_column -v`
Expected: FAIL — current code leaves the point at position 9 (BoL) because the
column fixup is deferred to paint. The other two should PASS (characterization).

- [ ] **Step 3: Implement eager `_vertical_move` in Layout**

In `src/ptedit/layout.py`, replace the `preferred_col`/`pin_preferred_col`
fields in `__init__` with:

```python
        self.goal_col: int = 0                       # column vertical moves aim for
        self.last_vertical_dest: Location | None = None   # where the last vertical move landed
```

Add `column_at` (near `offset_for_column`):

```python
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
```

Replace `_vertical_move`:

```python
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
```

- [ ] **Step 4: Strip the pin machinery from Display**

In `src/ptedit/display.py`:

- `_render_rows`: remove the `at_end` and `original_pt`-adjustment logic — the
  parameter list becomes `(self, start_row, end_row, mark, top_idx, pt, emit=True)`
  and the body loses the `pin_preferred_col` block (`display.py:172-178`). It
  still returns the cursor `Cell | None` (Task 2 removes that too). `pt_off` is
  computed from `pt` and never adjusted:

```python
            if 0 <= pt_off < delta:
                col = col_map[pt_off]
                toggle_pt = col
                cursor = Cell(row, col)
```

- `paint`: delete the `at_end` capture, every use of `adjusted_pt`
  (`_render_rows` now returns just the cursor), the trailing
  `preferred_col`/`pin_preferred_col` block (`display.py:281-286`), and instead
  save/restore the point:

```python
        original_pt = self.doc.get_point()
        ...
        self.doc.set_point(original_pt)
        self.prev_cursor = cursor
        return cursor
```

The `emit=False` no-scroll branch keeps working (it computes the cursor cell
without puts); Task 2 replaces it.

- [ ] **Step 5: Run the full suite and goldens**

Run: `uv run pytest -v`
Expected: all pass, including `tests/test_render_golden.py` unchanged (the
final point position per keystroke is identical; it's just computed at move
time instead of paint time).

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/layout.py src/ptedit/display.py tests/test_layout.py
git commit -m "refactor(layout): vertical moves land on the goal column eagerly

Commands now complete themselves: paint no longer moves the point to
apply a deferred preferred-column fixup. goal_col/last_vertical_dest
replace preferred_col/pin_preferred_col.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Cursor cell from the ladder — paint becomes read-only

**Files:**
- Modify: `src/ptedit/layout.py` (add `locate`)
- Modify: `src/ptedit/display.py` (paint computes cursor via `locate`; drop `emit` and `prev_cursor`)
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces: `Layout.locate(cursor: Location) -> tuple[int, int]` — (ladder line
  index, screen column); brackets the cursor itself. `Display._render_rows`
  becomes `(start_row, end_row, mark, top_idx, pt) -> None`.

- [ ] **Step 1: Write the failing test**

```python
def test_locate_cursor():
    doc = document.Document('abcd\nefgh\n')
    lay = layout.Layout(doc, cols=8, rows=4)
    lay.ensure_bracketed(doc.get_point())        # root the ladder at doc start
    doc.move_point(7)                            # 'g': line 1, col 2
    assert lay.locate(doc.get_point()) == (1, 2)  # ladder index, not absolute line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_layout.py::test_locate_cursor -v`
Expected: FAIL with `AttributeError: 'Layout' object has no attribute 'locate'`

- [ ] **Step 3: Implement `locate`**

```python
    def locate(self, cursor: Location) -> tuple[int, int]:
        """(ladder line index, screen column) for `cursor`; brackets it first."""
        i = self.ensure_bracketed(cursor)
        return i, self.column_at(self.bol_ladder[i], cursor)
```

- [ ] **Step 4: Rework `paint` around it**

In `src/ptedit/display.py`: delete the `prev_cursor` field and the `emit`
parameter. `_render_rows` no longer detects or returns the cursor cell (keep
the `toggle_pt` computation — it drives selection highlighting):

```python
            toggle_pt = col_map[pt_off] if 0 <= pt_off < delta else -1
            toggle_mark = col_map[mark_off] if 0 <= mark_off < delta else -1
```

`paint` computes the cell right after `find_top` (ladder indices are fresh at
that moment) and keeps the existing four branches for now:

```python
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
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass; goldens byte-identical (cursor cells aren't part of the
`put()` stream, and the emitted rows are unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/layout.py src/ptedit/display.py tests/test_layout.py
git commit -m "refactor(display): cursor cell from Layout.locate; paint is read-only

Drops the emit=False render mode and prev_cursor recovery — the cursor
cell is a pure ladder lookup after find_top.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Damage watermark + stale-highlight fix

**Files:**
- Modify: `src/ptedit/layout.py` (`damage_pos` replaces the two truncate flags)
- Modify: `src/ptedit/display.py` (single-flow paint; `prev_selection`)
- Test: `tests/test_display.py`

**Interfaces:**
- Produces: `Layout.damage_pos: int | None` and `Layout.take_damage() -> int | None`
  (read-and-clear). `Layout.change_handler(edit)` keeps its name until Task 5
  renames it. `Display._first_dirty_row(damage_pos: int, top_idx: int) -> int`.
  `Display.prev_selection: bool`.

**Semantics:** `damage_pos` = lowest document position whose on-screen bytes may
be stale. Every edit contributes `max(0, edit_pos - cols)` (the `cols` margin
covers soft-wrap pull-back, same rule as ladder truncation); multiple edits
between paints take the min. Positions are immune to ladder rebuilds and
evictions, which is exactly what the index-based flags weren't.

- [ ] **Step 1: Write the failing test (live bug)**

Append to `tests/test_display.py`:

```python
class GridScreen(display.Screen):
    """Accumulates a char+highlight grid like memory-mapped video RAM."""
    def __init__(self, height: int, width: int):
        super().__init__(height, width)
        self.clear()

    def clear(self):
        self.hi = [[False] * self.width for _ in range(self.height)]
        self.row = self.col = 0

    def move(self, row: int, col: int):
        self.row, self.col = row, col

    def put(self, ch: int, highlight: bool = False):
        if self.row < self.height:
            self.hi[self.row][self.col] = highlight
        self.col += 1
        if self.col >= self.width:
            self.col = 0
            self.row += 1

    def highlight_count(self) -> int:
        return sum(sum(row) for row in self.hi)


def test_clearing_mark_erases_highlight():
    """A cleared selection must not leave stale highlight on a stable window."""
    doc = document.Document('hello world ' * 40)
    scr = GridScreen(24, 80)
    dpy = display.Display(doc, scr)
    dpy.paint(None)
    mark = doc.get_point()
    doc.move_point(40)
    dpy.paint(mark)
    assert scr.highlight_count() == 40
    dpy.paint(None)                     # mark cleared; window otherwise stable
    assert scr.highlight_count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_display.py::test_clearing_mark_erases_highlight -v`
Expected: FAIL — second assert sees 40 (the `no_scroll` path emitted nothing).

- [ ] **Step 3: Implement the watermark in Layout**

In `Layout.__init__`, replace `last_truncate_keep`/`last_truncate_invalidated_top`
with:

```python
        self.damage_pos: int | None = None   # lowest doc position whose screen bytes may be stale
```

Add:

```python
    def take_damage(self) -> int | None:
        """Read and clear the damage watermark (once per frame)."""
        d = self.damage_pos
        self.damage_pos = None
        return d
```

Rewrite `change_handler` (drop the `old_top`/keep bookkeeping; the remap loop
is unchanged):

```python
    def change_handler(self, edit: Edit) -> None:
        """Record screen damage and repair the ladder through `edit`.

        Damage: any on-screen byte at or after `edit_pos - cols` may change
        (the cols margin covers soft-wrap pull-back, per docs/rendering.md).
        Ladder: remap entries through the edit; truncate at the first entry
        that fails either validity rule.
        """
        edit_pos = edit.get_change_start().position()
        dmg = max(0, edit_pos - self.cols)
        self.damage_pos = dmg if self.damage_pos is None else min(self.damage_pos, dmg)

        if not self.bol_ladder:
            return
        stats.sample('change_handler.ladder_len_before', float(len(self.bol_ladder)))
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
        stats.sample('change_handler.ladder_len_after', float(len(self.bol_ladder)))
```

`Ladder.truncate_to` is now unused — delete it (its `top` fixup moves nowhere;
`top` itself dies in Task 4).

- [ ] **Step 4: Single-flow paint in Display**

Add `self.prev_selection: bool = False` in `Display.__init__`. Replace the
branch block of `paint` (keep the pt/cursor bookkeeping from Task 2):

```python
        damage_pos = self.layout.take_damage()
        selection = mark is not None and mark.position() != pt.position()

        top_changed = self.find_top()
        top_idx = self.layout.bol_ladder.top

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
```

Add the watermark→row conversion:

```python
    def _first_dirty_row(self, damage_pos: int, top_idx: int) -> int:
        """First screen row whose bytes may differ from the video buffer, given
        document content at/after `damage_pos` may have changed. Row r is clean
        iff its line ends at or before damage_pos (i.e. the next BoL's position
        is <= damage_pos). Returns rows when the damage is entirely below the
        window (possible when an edit truncated rungs kept past the screen)."""
        lad = self.layout.bol_ladder
        dirty = 0
        for r in range(self.rows):
            i = top_idx + r + 1
            if i >= len(lad):
                break                       # no cached rung below: damage row stands
            if lad[i].position() <= damage_pos:
                dirty = r + 1
            else:
                break
        return dirty
```

Also update `change_handler` (`display.py:46-53`): it still remaps `top_loc`,
unchanged.

- [ ] **Step 5: Run the red test, then the full suite, then the perf gate**

Run: `uv run pytest tests/test_display.py::test_clearing_mark_erases_highlight -v`
Expected: PASS.

Run: `uv run pytest -v`
Expected: all pass. If a golden scenario includes a clear-mark frame its bytes
will legitimately change (the bug fix); inspect, then refresh with
`UPDATE_GOLDENS=1 uv run pytest tests/test_render_golden.py` and eyeball the diff.
Also `grep -rn "last_truncate\|no_scroll_with_selection" src tests tools` — fix
any stragglers (e.g. stats-key assertions).

Run the perf gate (see Global Constraints). `insert` exercises
`_first_dirty_row` every frame — it must hold within ~10% of 369 fps.

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/layout.py src/ptedit/display.py tests/test_display.py
git commit -m "refactor(display): damage watermark replaces truncate flags; fix stale highlight

Screen damage is one document position (min over edits, cols margin).
paint classifies to a single first-dirty row. Tracks prev_selection so
clearing the mark repaints instead of leaving stale highlight (bug).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Ladder single-owner — `ensure_row` / `render_lines` / `make_room`; drop `Ladder.top`

**Files:**
- Modify: `src/ptedit/layout.py` (`Ladder` slims down; new row API)
- Modify: `src/ptedit/display.py` (`find_top` returns `(top_idx, changed)`; `_render_rows` iterates `render_lines`)
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces:
  - `Layout.bol(i: int) -> Location` — read-only rung accessor.
  - `Layout.ensure_row(i: int) -> Location` — extends the ladder until entry `i`
    exists; returns that BoL, or the end-of-document location if the document
    is shorter.
  - `Layout.render_lines(i: int, count: int) -> Iterator[tuple[bytes, list[int]]]`
    — formats rows `[i, i+count)` sequentially, caching new BoLs; the point
    flows forward across rows exactly as `_render_rows` does today.
  - `Layout.make_room(top_idx: int, rows: int) -> int` — evicts leading rungs so
    the window can be appended without mid-paint eviction; returns adjusted index.
  - `Display.find_top() -> tuple[int, bool]` — (top index, top changed).
- `Ladder` keeps only capped `append` and `reset`; `top` and `truncate_to` are gone.

**Why `make_room`:** `Ladder.append` evicts entry 0 when full, shifting every
index. Today `_render_rows` survives by formatting sequentially, but any
index-based access during paint is one eviction away from an off-by-one (a
latent hazard in the current code too). Guaranteeing up front that
`top_idx + rows <= MAX` makes indices stable for the whole frame.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_lines_formats_and_caches():
    doc = document.Document('aaa\nbbb\nccc\n')
    lay = layout.Layout(doc, cols=8, rows=4)
    lay.reanchor(doc.get_point())
    lines = [bytes(l).rstrip(b'\x00') for l, _ in lay.render_lines(0, 3)]
    assert lines == [b'aaa\n', b'bbb\n', b'ccc\n']
    assert len(lay.bol_ladder) == 3           # anchor + BoLs for rows 1 and 2


def test_make_room_prevents_mid_paint_eviction():
    doc = document.Document('x\n' * 200)
    lay = layout.Layout(doc, cols=16, rows=8)
    lay.reanchor(doc.get_point())
    lay.ensure_row(layout.Ladder.MAX - 1)     # fill the ladder to capacity
    assert len(lay.bol_ladder) == layout.Ladder.MAX
    target = lay.bol_ladder[60]
    top = lay.make_room(60, 8)                # 60 + 8 - 64 = 4 rungs over
    assert top == 56
    assert lay.bol_ladder[top] is target
    assert len(lay.bol_ladder) == layout.Ladder.MAX - 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout.py -k "render_lines or make_room" -v`
Expected: FAIL with `AttributeError` (`render_lines` / `ensure_row` / `make_room`).

- [ ] **Step 3: Implement the Layout row API**

`Ladder` becomes:

```python
class Ladder(list[Location]):
    """BoL rungs for the visible region and its neighborhood, per
    docs/rendering.md. Python subclasses `list` (O(1) indexing); MAX is
    enforced on append by dropping the oldest rung. The `top` index lives
    with Display's frame state, not here."""
    MAX = 64

    def append(self, loc: Location) -> None:
        if len(self) == self.MAX:
            del self[0]
        super().append(loc)

    def reset(self, anchor: Location) -> None:
        """Discard everything; seed with a single anchor."""
        self.clear()
        super().append(anchor)
```

Remove the `self.bol_ladder.top` assignments in `reanchor` (`layout.py:155`)
and anywhere else (`grep -n "\.top" src/ptedit/layout.py src/ptedit/display.py`).

Add to `Layout`:

```python
    def bol(self, i: int) -> Location:
        """Read-only rung accessor for Display."""
        return self.bol_ladder[i]

    def ensure_row(self, i: int) -> Location:
        """Extend the ladder until entry `i` exists; return that BoL, or the
        end-of-document location if the document has fewer lines."""
        lad = self.bol_ladder
        while i >= len(lad):
            self.doc.set_point(lad[-1])
            self.format_line()
            if self.doc.at_end():
                return self.doc.get_point()
            lad.append(self.doc.get_point())
        return lad[i]

    def render_lines(self, i: int, count: int):
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
        without Ladder.append evicting mid-frame; returns the adjusted index."""
        overflow = top_idx + rows - Ladder.MAX
        if overflow > 0:
            del self.bol_ladder[:overflow]
            top_idx -= overflow
        return top_idx
```

- [ ] **Step 4: Rewire Display**

`find_top` (full replacement — same logic, index returned instead of stored):

```python
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
```

`paint`: `top_idx, top_changed = self.find_top()` (delete the
`self.layout.bol_ladder.top` read). `_render_rows` (full replacement):

```python
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
```

Also update `_first_dirty_row` and any other `self.layout.bol_ladder[...]`
reads in Display to go through `self.layout.bol(i)` / lengths via
`len(self.layout.bol_ladder)` is fine to keep (read-only), or add a
`Layout.rung_count()` if you prefer zero direct touches — reads are acceptable,
writes are not: `grep -n "bol_ladder.append\|bol_ladder\[.*\] *=" src/ptedit/display.py`
must come back empty.

- [ ] **Step 5: Update ladder-shape tests, run everything**

`grep -n "\.top\|truncate_to" tests/*.py` — update `test_layout.py` /
`test_display.py` assertions that referenced `Ladder.top` (e.g.
`test_reanchor_lad_shape_invariant`): the shape contract is now just the rung
list; top expectations move to `find_top`'s return value.

Run: `uv run pytest -v` — all pass; goldens unchanged.
Run the perf gate — `render_lines` is the same loop as before (point flows
sequentially), so expect noise-level deltas only.

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/layout.py src/ptedit/display.py tests/test_layout.py tests/test_display.py
git commit -m "refactor(layout): ladder has one owner; make_room stabilizes frame indices

Display consumes rows via ensure_row/render_lines/bol and never writes
the ladder. Ladder.top is gone — find_top returns the index. make_room
guarantees no mid-frame eviction (previously a latent off-by-one).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Single `on_change` hook; undo/redo/squash invalidate wholesale

**Files:**
- Modify: `src/ptedit/document.py` (single hook, `_notify(edit | None)`)
- Modify: `src/ptedit/layout.py` (`note_change` rename + `invalidate`)
- Modify: `src/ptedit/display.py` (`note_change(edit | None)`)
- Modify: `src/ptedit/editor.py` (no watcher; explicit mark clears)
- Modify: `src/ptedit/controller.py` (no watcher; autosave from the key loop)
- Modify: `tests/test_layout.py:121,144,166` (`doc.watch(...)` → hook assignment)
- Test: `tests/test_display.py`

**Interfaces:**
- Produces: `Document.on_change: Callable[[Edit | None], None] | None` — the
  single change hook. `edit` is the applied `Edit` for insert/delete/replace;
  `None` means "wholesale change, reset caches" (undo/redo/squash).
  `Layout.note_change(edit: Edit)` (renamed from `change_handler`),
  `Layout.invalidate()`, `Display.note_change(edit: Edit | None)`.
  `Display.__init__` assigns `doc.on_change = self.note_change` (the view is
  the hook's one consumer; standalone-Display test fixtures keep working).
- `Document.watch` / `notify_watchers` / `_watchers` are deleted.

**Design note:** undo correctness previously depended on remapping ladder
entries through the *previous* edit (the pointer moves before notification) —
it holds today only via an undocumented chain (sorted-truncation + recenter).
The new rule is one sentence: *anything but a forward edit resets the caches.*
Cost: one reanchor per undo/redo — explicitly exempt from the perf gate.

- [ ] **Step 1: Write the pinning test (green before and after)**

Append to `tests/test_display.py` (uses `GridScreen` from Task 3 — extend it to
also record chars):

```python
def test_undo_screen_matches_fresh_render():
    """After undo, the accumulated screen must equal a from-scratch render."""
    text = ('the quick brown fox jumps over the lazy dog. ' * 30)

    def frame_chars(scr):
        return [''.join(chr(c) for c in row) for row in scr.chars]

    doc = document.Document(text)
    scr = GridScreen(24, 80)
    dpy = display.Display(doc, scr)
    dpy.paint(None)
    doc.move_point(200)
    doc.insert('hello world ')
    dpy.paint(None)
    for _ in range(5):
        doc.move_point(1)
        dpy.paint(None)
    doc.undo()
    dpy.paint(None)

    ref_doc = document.Document(doc.get_data())
    ref_doc.move_point(doc.get_point().position())
    ref_scr = GridScreen(24, 80)
    ref_dpy = display.Display(ref_doc, ref_scr)
    ref_dpy.paint(None)

    assert frame_chars(scr) == frame_chars(ref_scr)
```

Extend `GridScreen` with a `chars` grid alongside `hi` (full replacement of
the two methods from Task 3):

```python
    def clear(self):
        self.chars = [[ord(' ')] * self.width for _ in range(self.height)]
        self.hi = [[False] * self.width for _ in range(self.height)]
        self.row = self.col = 0

    def put(self, ch: int, highlight: bool = False):
        if self.row < self.height:
            self.chars[self.row][self.col] = ch if 32 <= ch < 127 else ord(' ')
            self.hi[self.row][self.col] = highlight
        self.col += 1
        if self.col >= self.width:
            self.col = 0
            self.row += 1
```

Run: `uv run pytest tests/test_display.py::test_undo_screen_matches_fresh_render -v`
Expected: PASS (pins current behavior so the refactor can't silently break undo).

- [ ] **Step 2: Rework Document notification**

In `src/ptedit/document.py`, replace `_watchers`/`watch`/`notify_watchers`:

```python
OnChange = Callable[['Edit | None'], None]


def mutator(method: Callable[Concatenate[Document, P], R]) -> Callable[Concatenate[Document, P], R]:
    """Wrap a forward edit: notify the change hook with the applied Edit."""
    def wrapped(self: Document, *args: P.args, **kwargs: P.kwargs) -> R:
        retval = method(self, *args, **kwargs)
        self._notify(self._edit)
        return retval
    return wrapped
```

```python
    def __init__(self, s: str = '') -> None:
        # The single change hook: called with the applied Edit after a forward
        # edit, or None after a wholesale change (undo/redo/squash) meaning
        # "reset any cached view of the piece chain".
        self.on_change: OnChange | None = None
        ...

    def _notify(self, edit: Edit | None) -> None:
        self.dirty = True
        if self.on_change is not None:
            self.on_change(edit)
```

`insert`/`delete`/`replace` keep `@mutator`. `squash`, `undo`, `redo` drop the
decorator and end with `self._notify(None)`:

```python
    def squash(self) -> None:
        self._reset(self.get_data())
        self._notify(None)

    def undo(self) -> Document:
        if self._edit.prev:
            self.set_point(self._edit.undo())
            self._edit = self._edit.prev
        self._notify(None)
        return self

    def redo(self) -> Document:
        if self._edit.next:
            self._edit = self._edit.next
            self.set_point(self._edit.redo())
        self._notify(None)
        return self
```

- [ ] **Step 3: Layout rename + invalidate; Display becomes the hook**

`src/ptedit/layout.py`: rename `change_handler` → `note_change`; add:

```python
    def invalidate(self) -> None:
        """Wholesale cache reset (undo/redo/squash): the next paint re-anchors."""
        self.bol_ladder.clear()
        self.damage_pos = None
        self.last_vertical_dest = None
```

`src/ptedit/display.py`: replace `self.doc.watch(self.change_handler)` with
`doc.on_change = self.note_change`, and replace `change_handler` with:

```python
    def note_change(self, edit: Edit | None) -> None:
        """Document change hook. Forward edits repair the caches incrementally
        (the typing hot path); anything else resets them — one rule, no
        staleness reasoning."""
        if edit is None:
            self.layout.invalidate()
            self.top_loc = None
            return
        self.layout.note_change(edit)
        if self.top_loc is not None:
            self.top_loc = edit.remap_location(self.top_loc)
```

- [ ] **Step 4: Editor and Controller shed their watchers**

`src/ptedit/editor.py`: delete `self.doc.watch(self.change_handler)` and
`change_handler`. The mark's lifecycle becomes explicit in the commands that
end it — add `self.mark = None` to `squash`, `undo`, and `redo`:

```python
    def undo(self) -> None:
        self.mark = None            # locations don't survive chain surgery
        self.doc.undo()

    def redo(self) -> None:
        self.mark = None
        self.doc.redo()

    def squash(self) -> None:
        self.mark = None
        pos = self.doc.get_point().position()
        self.doc.squash()
        self.doc.set_point_start().move_point(pos)
```

(`insert`/`delete_*`/`cut`/`paste` already clear the mark via
`_kill_region`/`_clip_region`.)

`src/ptedit/controller.py`: delete `self.doc.watch(self.change_handler)` and
`change_handler`; drive autosave from the key loop instead (counts
keystrokes-while-dirty rather than raw mutations — same ~10-keystroke backup
cadence):

```python
            try:
                key = self.getch()
                logging.info(f'key ${key:02x}')
                self.dispatch(key)
                if self.doc.dirty:
                    self.autosave()
            except KeyboardInterrupt:
                self.quit()
```

- [ ] **Step 5: Update fixtures, run everything, perf gate**

`tests/test_layout.py:121,144,166`: `doc.watch(lay.change_handler)` →
`doc.on_change = lay.note_change`.
`grep -rn "watch\|change_handler" src tests tools` — no stragglers.

Run: `uv run pytest -v` — all pass, including the Step-1 undo pinning test
(now passing via full invalidation instead of the accidental chain).

Run the perf gate. Note for the log: `insert` may *improve* because the old
watcher autosaved a backup file every 10 mutations inside the perftest loop;
that I/O artifact is gone. Record both numbers honestly in Task 9.

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/document.py src/ptedit/layout.py src/ptedit/display.py \
        src/ptedit/editor.py src/ptedit/controller.py tests/test_layout.py tests/test_display.py
git commit -m "refactor(document): single on_change hook; undo/redo/squash reset caches

Replaces the ordered watcher list with one named hook consumed by
Display. Incremental ladder repair now applies only to forward edits;
undo correctness no longer rests on remapping through the wrong edit.
Autosave moves to the controller key loop; Editor clears the mark
explicitly in the commands that end it.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: isearch mode ownership moves to the Controller

**Files:**
- Modify: `src/ptedit/editor.py` (public `isearch_insert`/`isearch_delete`; no mode branching)
- Modify: `src/ptedit/controller.py` (`_act` routes bare ints per mode; ISEARCH keymap)
- Test: `tests/test_editor.py`

**Interfaces:**
- Produces: `Editor.isearch_insert(c: str)`, `Editor.isearch_delete()` (renamed
  from `_isearch_insert`/`_isearch_delete`). `Editor.insert(ch: int)` and
  `Editor.delete_backward_char()` no longer check `isearch_dir`.

- [ ] **Step 1: Write the pinning test (green before and after)**

Append to `tests/test_editor.py`:

```python
def test_isearch_keys_route_to_search_not_document(tmp_path):
    f = tmp_path / 't.txt'
    f.write_text('hello world\n')
    ctrl = controller.Controller(str(f), Screen(24, 80))
    ctrl.dispatch(controller.ctrl('S'))          # enter isearch
    for c in 'world':
        ctrl.dispatch(ord(c))
    assert ctrl.ed.isearch_text == 'world'
    assert ctrl.doc.get_point().position() == 11          # point after the match
    assert ctrl.doc.get_data() == 'hello world\n'         # nothing inserted
    ctrl.dispatch(127)                                    # isearch backspace
    assert ctrl.ed.isearch_text == 'worl'
```

(Add `from ptedit import controller` and `from ptedit.screen import Screen` to
the imports.)

Run: `uv run pytest tests/test_editor.py -k isearch_keys -v` — PASS (pins the
behavior the refactor must preserve).

- [ ] **Step 2: Refactor Editor**

Rename `_isearch_insert` → `isearch_insert` and `_isearch_delete` →
`isearch_delete` (update the internal callers). Strip mode branching:

```python
    def insert(self, ch: int) -> None:
        self._kill_region()
        c = chr(ch)
        if self.overwrite_mode:
            self.doc.replace(c)
        else:
            self.doc.insert(c)

    def delete_backward_char(self) -> None:
        self._kill_region()
        self.doc.delete(-1)
```

- [ ] **Step 3: Route by mode in the Controller**

In the ISEARCH keymap, bind `127: ed.isearch_delete` (keep `**printable` so
printable keys resolve to an action instead of falling through). In `_act`,
interpret a bare int according to the mode that owns the keymap:

```python
    def _act(self, actions: list[Action]) -> None:
        for action in actions:
            if callable(action):
                action()
            elif isinstance(action, KeyMode):
                self.mode = action
            elif self.mode == KeyMode.ISEARCH:
                self.ed.isearch_insert(chr(action))
            else:
                self.ed.insert(action)
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -v`
Expected: all pass — the Step-1 test proves printable keys still extend the
search, and `Editor` no longer consults `isearch_dir` to decide what a
keypress means (`grep -n "isearch" src/ptedit/editor.py` shows only
search-state methods).

- [ ] **Step 5: Commit**

```bash
git add src/ptedit/editor.py src/ptedit/controller.py tests/test_editor.py
git commit -m "refactor(controller): isearch key routing owned by the mode that names it

Editor commands stop branching on isearch state; the Controller (which
owns KeyMode) routes bare-int keys to isearch_insert or insert.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Identity equality for Piece

**Files:**
- Modify: `src/ptedit/piece.py:10,81,112` (decorators)
- Test: `tests/test_piece.py`

**Why:** the generated dataclass `__eq__` compares pieces field-by-field
(including recursive `prev`/`next` — saved from pathology only by tuple
identity shortcuts, and from false positives only by the debug `id` counter).
Chain pieces are identity objects; say so. Side benefit: `Location`'s hot
`p != other.piece` loops become single pointer compares.

- [ ] **Step 1: Write the test**

Append to `tests/test_piece.py`:

```python
def test_piece_equality_is_identity():
    a = PrimaryPiece(data='abc')
    b = PrimaryPiece(data='abc')
    assert a == a and a != b
    assert Location(a, 1) == Location(a, 1)
    assert Location(a, 1) != Location(b, 1)
```

(Import `Location` from `ptedit.location`.) This passes today only because the
debug `id` field differs — the change makes the intent structural.

- [ ] **Step 2: Apply `eq=False`**

```python
@dataclass(kw_only=True, eq=False)
class Piece:
    ...

@dataclass(repr=False, eq=False)
class PrimaryPiece(Piece):
    ...

@dataclass(repr=False, eq=False)
class SecondaryPiece(Piece):
    ...
```

- [ ] **Step 3: Run the suite**

Run: `uv run pytest -v` — all pass. `grep -rn "== *Location\|Location(.*) *==" tests src`
to confirm no value-equality-across-pieces assumptions exist.

- [ ] **Step 4: Commit**

```bash
git add src/ptedit/piece.py tests/test_piece.py
git commit -m "refactor(piece): identity equality for chain pieces

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Status line without extra document walks

**Files:**
- Modify: `src/ptedit/controller.py:154-177` (`status_message`)

`status_message` currently walks the whole document four times per keystroke
(`get_data()` twice, `len(self.doc)` rebuilding it a third time, plus
`pt.position()`), silently dominating the frame cost the perftests measure
around. Reuse the two strings it already builds:

- [ ] **Step 1: Apply the change**

```python
            pt_data = self.doc.get_data(None, pt)
            doc_data = self.doc.get_data()
            ...
                f"pos {len(pt_data)}/{len(doc_data)}",
```

(replacing `f"pos {pt.position()}/{len(self.doc)}"`; delete the now-unused
`pt` position walk if nothing else uses it).

- [ ] **Step 2: Run the suite and commit**

Run: `uv run pytest -v` — all pass (no test renders the status line's pos field
from a stale walk).

```bash
git add src/ptedit/controller.py
git commit -m "perf(controller): status line reuses its own document walks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Documentation + final perf table

**Files:**
- Modify: `docs/rendering.md` (Phase 2, Ladder storage, new Damage/Undo rules)
- Modify: `docs/plans/perf-baseline.md` (append results table)
- Modify: `README.md` (MVC section: paint-is-read-only, single hook)

- [ ] **Step 1: Update `docs/rendering.md`**

Replace the Phase 2 table and add the damage/undo contract. Replacement for the
*Phase 2: Screen Update* section:

```markdown
### Phase 2: Screen Update

Each edit records **damage**: the lowest document position whose on-screen
bytes may have changed, `max(0, edit_pos - cols)` (the `cols` margin covers
soft-wrap pull-back; multiple edits take the min). Positions — unlike ladder
indices — survive ladder rebuilds and evictions between edit and paint.

Paint reduces every case to one number, the **first dirty row**:

| Condition | first dirty row |
|-----------|-----------------|
| `top` changed, or a selection is active now or was last frame | 0 (full redraw) |
| damage recorded | the row containing the damage position (rows above are byte-stable) |
| otherwise | `rows` (emit zero cells) |

then re-renders rows `[first_dirty, rows)`. On the 6502 the damage watermark
is one 16-bit position and the dirty row one byte; the Scroll sub-case
(video-RAM block move, then dirty from the exposed region) slots into the
same scheme.
```

Update the *Storage* paragraph: the Python `Ladder` no longer carries `top`
(Display's `find_top` derives and returns the index each frame; `make_room`
evicts leading rungs pre-frame so appends never shift indices mid-paint —
the Forth ring keeps `first/top/last` as before). Update *Validity / Remap*
and *Sticky top* to add the wholesale rule:

```markdown
Incremental remap applies only to forward edits (the typing hot path).
Undo, redo, and squash invalidate the ladder and the sticky top outright —
one reanchor per undo beats reasoning about remapping locations through an
edit whose pieces just got swapped back in.
```

Also strike the resolved “paint completes vertical moves” behavior anywhere it
is implied (preferred-column fixup is now eager in `Layout._vertical_move`).

- [ ] **Step 2: Update `README.md` MVC paragraph**

In the table row for View, and the paragraph below it, state the new
invariants: *`Display.paint` reads the document (point saved/restored) and
never mutates model or movement state; `Document.on_change` is a single hook
consumed by `Display`; vertical moves land on their goal column at command
time.*

- [ ] **Step 3: Capture final perf numbers**

Run the gate command (Global Constraints) and append to
`docs/plans/perf-baseline.md`:

```markdown
## MVC cleanup (2026-07-11 plan)

Captured at <commit> against `tests/alice1flow.asc`, mock-Screen path.

| scenario       | pre-cleanup (`e7dae25`) | post-cleanup | ratio |
|----------------|-------------------------|--------------|-------|
| insert         | 369                     | ...          | ...   |
| up_from_end    | 1434                    | ...          | ...   |
| pgup_from_end  | 258                     | ...          | ...   |
| pgdn_from_top  | 348                     | ...          | ...   |

Notes: `insert` is flattered by removing the perftest autosave artifact
(the old change watcher wrote a backup file every 10 mutations inside the
timing loop). Undo/redo now cost one reanchor each — accepted trade
(simplicity on rare paths).
```

Gate: the three navigation scenarios within ~10% of baseline; `insert` at or
above baseline. If a scenario regresses past the gate, profile before and
after (`tools/profile_perf.py`) and fix or explicitly justify in the table.

- [ ] **Step 4: Full suite one last time, commit**

Run: `uv run pytest -v` and the perf gate.

```bash
git add docs/rendering.md docs/plans/perf-baseline.md README.md
git commit -m "docs(rendering): damage watermark, single-owner ladder, wholesale undo invalidation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Follow-ups (out of scope, recorded for later)

- Remove the `goal_col = 0` at-doc-end parity guard in `_vertical_move` so
  up-arrow from EOD keeps the EOD column (Emacs-like; one-line change plus a
  golden refresh).
- `format_line` wrap policy: consume the boundary space instead of emitting a
  length-1 `' '` line (noted in rendering.md).
- Status line: maintain newline counts incrementally instead of two full walks.
- Consider seeding the perftest `insert` scenario with autosave disabled
  explicitly, so the measurement never depends on notification plumbing.
