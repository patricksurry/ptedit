# Efficient Rendering

On vintage hardware even repainting an 80 × 24 screen is expensive.
This document describes how we update that screen efficiently.

Drawing each `rows × cols` frame from the piece table requires:

1. Picking a top-of-screen anchor — the beginning-of-line (BoL)
   for the first screen row.
2. Walking forward from the anchor, formatting `rows` visual lines:
   tabs, escapes for non-printables, soft-wrap at `cols`.
3. Drawing the cursor at the document point and highlighting the
   region between point and mark (if any).

With no other context, finding the top-of-screen anchor requires a
backward scan to the nearest line break and then a forward walk of
the off-screen rows up to the point. The backward scan is unbounded
in the worst case (a long unwrapped paragraph with no `\n`); the
forward render is bounded by `rows × cols`. We want to amortize
both across consecutive frames.

## Constraints

On vintage hardware both memory and cycles are extremely limited.
The renderer should:

- Use a memory-mapped video buffer as the only copy of displayed
  bytes (beyond the piece table itself). Updating a cell is one
  byte write to the buffer.
- Keep state minimal — no shadow screen buffer or other large
  duplicates of document data.
- Use no dynamic allocation.

## Cast

Two classes split the rendering work (see the README for the full
MVC picture):

```
  Document ...... piece chain + point (the cursor Location)
     |  on_change(edit | None)         ^ commands move the point
     v                                 |
  Layout ........ ladder cache of visual-line starts; format_line
     |            (doc chars -> screen bytes); line/page moves
     v
  Display ....... find_top (scrolling) + paint (redraw) -> Screen
```

Terms used throughout:

- **visual line / BoL**: a line as displayed — ended by a hard
  `\n` or a soft wrap at `cols`; BoL is its beginning-of-line
  document position.
- **ladder**: the cached BoL marks near the screen (next section).
- **paint**: `Display`'s once-per-frame entry point; decides what
  to redraw and emits it.
- **forward edit**: insert/delete/replace — as opposed to undo,
  redo, and squash, which rewire the piece chain wholesale.
- **damage** (`damage_pos`): the lowest document position whose
  on-screen bytes may be stale (Phase 2).
- **reanchor**: rebuild the ladder from the nearest hard newline
  before the cursor (Phase 1).

## Invariants

The renderer is organized around five invariants; every section
below is a mechanism serving one of them.

1. Commands complete themselves — cursor motion (including the
   goal column of vertical moves) is resolved at command time,
   never fixed up during a paint.
2. `paint` is read-only: it saves and restores the point and
   mutates nothing outside the screen and its own frame state.
3. `Layout` is the ladder's sole owner; `Display` reaches the
   cache only through `bol` / `ensure_row` / `render_lines` /
   `make_room`.
4. Screen damage is a single document position (`damage_pos`);
   paint reduces every redraw decision to one first-dirty row.
5. Cache repair is incremental only for forward edits; undo, redo,
   and squash invalidate wholesale (one reanchor beats reasoning
   about remapping through chain surgery).

## Ladder State

The renderer maintains a **ladder** of BoL marks — one per visual
line on or near the screen. Three indices identify regions:

- `first`: First valid line anchor (nearest document start).
- `top`:   Anchor displayed at screen row 0.
- `last`:  One past the last valid anchor (nearest document end).

The ladder spans `[first, last)` (half-open). The visible region
corresponds to the `rows` entries starting at `top`.

The ladder typically extends past the visible window in both
directions. *Above* `top` because re-anchoring lands on the nearest
newline before the screen, so those rungs come along for free.
*Below* `top + rows` because scrolling and edits often leave
already-formatted rungs we can preserve rather than discard.

### Storage

The Forth/6502 port stores the ladder as a 64-slot ring buffer
($2^6 = 64$ entries × 4 bytes per `Location` = 256 bytes). The
three indices are byte offsets into the ring; index arithmetic is
modulo size.

The Python reference implementation subclasses `list[Location]`
instead — O(1) indexing, `MAX = 64` enforced manually on `append`
(oldest entry dropped on overflow). `first == 0` always; `last ==
len(slots)`. Unlike the Forth ring, the Python `Ladder` does **not**
carry `top`: `Display.find_top` derives the screen-row-0 index fresh
each frame (sticky-top math against last frame's `top_loc`, or a
recenter walk) and hands it back as a plain `int`, `top_idx`, that
never outlives the frame. `Layout.make_room` evicts leading rungs
*before* a frame's rows are appended, so `Ladder.append`'s own
overflow-eviction (drop-oldest at `MAX`) never fires mid-frame and
shifts `top_idx` out from under the renderer. `Layout` is the
ladder's sole owner — `bol`, `ensure_row`, `render_lines`, and
`make_room` are its accessors; `Display` only reads `len(bol_ladder)`
for stats/bounds checks and never appends or truncates it directly.
The algorithm is identical to the Forth contract; the data-structure
mechanics diverge for Python ergonomics.

## Rendering Cycle

Each frame update follows a two-phase process.

### Phase 1: Update Ladder

In what follows, the cursor's *position* means its document
position; comparisons against ladder slots are against the document
position stored at that slot (`ladder[i].pos`).

1. **If a document edit occurred:** Walk `[first, last)` and translate
   each entry through the edit (see *Validity / Remap* below); truncate
   at the first entry that can't be preserved.

2. **Locate the cursor relative to the ladder.** A linear scan finds
   which (if any) ladder line contains the cursor. Three cases:

   - **Bracketed** — cursor is within the cached range. If the
     containing line falls in the visible-window guard zone, shift
     `top` (Scroll). Otherwise no ladder change.

   - **Just past `last`** (cursor at most `rows` lines beyond the
     last cached BoL): format forward from `last` to extend the
     ladder (Extension). The threshold is `rows` because extending
     further costs more than a full redraw from a fresh anchor.

   - **Otherwise** (cursor before `first`, large forward jump, or
     truncation orphaned the cursor): **Re-anchor.** Backscan to a
     hard newline, reset the ladder rooted there, forward-format
     until cursor is bracketed.

A pure selection change (mark moves, point does not, no edit) skips
Phase 1 entirely.

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

Python folds the doc's "Scroll" sub-case into the `top`-changed full
redraw: terminal block-copy is out of scope, and the cached ladder primes
`format_line` either way. A Forth/6502 port should distinguish them to
exploit video-RAM block moves.

## Validity / Remap

When a document edit occurs, the `Edit` object owns the translation:
`edit.remap_location(loc)` returns

- `loc` itself if the edit didn't touch `loc.piece`.
- `Location(pre, offset)` if `loc.piece` was split and `loc.offset`
  lands in the prefix.
- `Location(post, offset - post_start)` if it lands in the suffix.
- `None` if the offset fell into a deleted slice, or the edit
  unlinked multiple pieces (we don't try to handle multi-piece
  unlinks; the caller drops the entry).

After remap, an additional **`cols` margin** rule applies: drop the
entry if `remapped.position() + cols >= edit_pos`. This guards
against soft-wrap propagation — an edit on visual line N can
change the wrap point of visual line N-1 if a word is "pulled"
up or "pushed" down (see example below). Truncating forward from
the first failure is correct by construction: ladder entries are
sorted by document position, so once one fails either rule, all
later entries are at higher positions (= closer to or past the
edit) and would fail too.

The remap matters because, for a freshly-opened document, the
entire ladder references a single piece `P`. The first edit splits
`P` into `pre / ins / post` and unlinks `P` — *every* ladder entry
would fail rule 1 without the remap, wiping the ladder on each
keystroke. With the remap, entries with `offset < len(pre)` migrate
cleanly to `pre`.

Incremental remap applies only to forward edits (the typing hot path).
Undo, redo, and squash invalidate the ladder and the sticky top outright —
one reanchor per undo beats reasoning about remapping locations through an
edit whose pieces just got swapped back in. `Document.on_change` is the
single hook this dispatches on: called with the applied `Edit` after a
forward edit (incremental path above), or with `None` after undo/redo/
squash, which `Display.note_change` maps straight to
`Layout.invalidate()` (clears the ladder and the damage watermark) plus
resetting `top_loc` to `None` so the next `find_top` recenters.

### Example: Wrap propagation (motivating the `cols` margin)

```
cols = 20
before:  "some short words supercalifragilistic..."
                          ^pos 17 (BoL of visual line 2)
                          line 1 = "some short words "      (wrap after space)
                          line 2 = "supercalifragilistic"   (no wrap)

edit:    insert ' ' after "super" (pos 22)

after:   "some short words super califragilistic..."
                                 ^new wrap point at pos 23
                          line 1 = "some short words super " (absorbed "super ")
                          line 2 = "califragilistic..."
```

The edit at pos 22 changed the BoL of visual line 2 (from 17 to 23).
Any ladder entry within `cols` of the edit is discarded.

## Sticky top & guard-zone scrolling

`find_top` records the document position shown at screen row 0 as
`top_loc` (a `Location` that gets remapped through forward edits via
the same `edit.remap_location`, or reset to `None` outright on
undo/redo/squash — see *Validity / Remap*'s wholesale-invalidation
rule). On the next frame:

- If `top_loc` is still in the ladder AND the cursor's row in window
  satisfies `cur_idx < top_idx + rows`: **sticky** — keep last
  frame's top, clamping `delta = cur_idx - top_idx` to
  `[guard_rows, rows - guard_rows - 1]` and shifting `top` only if
  the cursor entered a guard zone. Returns "top changed" iff the
  resulting `top_loc` differs from the old one (this is what
  drives Phase 2's Full-vs-No-scroll decision).
- Otherwise: **recenter** — walk back `preferred_row` lines from
  the cursor via `bol_to_prev_bol`, then anchor `top` there.

The first paint of a frame after `find_top` (case = "no top change,
no edit, no selection") can emit zero cells: the screen is
byte-identical to the last frame; only the caller's terminal-cursor
move is needed.

## Open questions & explored alternatives

- **Per-piece newline counts.** Enables fast "what line is point on?"
  via piece-chain walk; useful for status-bar line numbers, but
  orthogonal to the ladder and not currently implemented.

- **Per-entry cache rescue across edits.** Pre-Stage 2 the renderer
  walked position arithmetic to reconstruct each cached BoL in the
  new piece chain after every edit (~50 lines, several edge cases).
  Removed in favor of the `Edit.remap_location` approach which is
  cleaner and (after fixing the `top_loc` staleness bug) recovers
  the same performance.

- **Deep backscan in `reanchor`.** A natural intuition: when
  `reanchor` builds a ladder, keep backscanning past *several*
  newlines so the resulting ladder is big enough to absorb a few
  upward steps before the next rebuild — say, half a screen of
  chars. Tried (`rows * cols / 2` threshold) — **perf regression**,
  not improvement: `insert` -24%, `up_from_end` -21%. Each reanchor's
  cost grew ~5× and the rare-cascade-during-recenter benefit didn't
  compensate. The dominant `insert` cost is `Layout.note_change`
  truncating below the cursor each step, not reanchor itself. Net:
  shallow `reanchor` stays.

- **`bol_to_prev_bol` fallback contract (resolved).** Earlier the
  fallback walked `move_point(-1)` + `reanchor(cursor_arg)` +
  `set_point(lad[-2])`, assuming `lad[-1]` was strictly past
  `cursor_arg` (so `lad[-2]` was the previous visual BoL). That
  assumption breaks whenever `cursor_arg` is itself the BoL of a
  **length-1 visual line** — the `set_point(lad[-2])` then skips
  that line. Length-1 lines occur as empty paragraphs (lone `\n`)
  AND as soft-wrap artifacts (e.g. doc `'abcd efgh'` cols=4 →
  `'abcd'` / `' '` / `'efgh'`, BoLs at 0, 4, 5).

  Fixed (commit `3b7c420`) by replacing the special-case logic with
  a uniform `lad[line_index(cursor_arg)]` — `line_index` naturally
  returns the index of the visual line containing `cursor_arg`,
  whether that line is length-1 or normal. Pinned by
  `test_bol_to_prev_bol_lands_on_empty_line` (empty paragraph) and
  `test_bol_to_prev_bol_lands_on_length1_soft_wrap_line` (soft-wrap
  artifact); `test_reanchor_lad_shape_invariant` documents the
  ladder-shape contract that future reanchor changes must preserve.

  Aside: the lone-`' '`-line wrap (`'abcd'`/`' '`/`'efgh'`) is itself
  arguably a `format_line` wrap-policy wart — a more natural wrap
  would consume the space at the boundary (`'abcd'`/`'efgh'`).
  Separate concern; not pursued here.

- **Smart reanchor during recenter walks.** When `find_top`'s
  recenter calls `bol_to_prev_bol × preferred_row` and each hits
  the fallback, we get a cascade of reanchors. A version that
  *prepends* one BoL at a time was tried (`_extend_backward`); it
  removed the per-call rebuild but ran `preferred_row` backscans
  per recenter walk (one per upward step) instead of one per
  cascade. Net worse for the `insert` perftest. A batched
  "prepend the whole previous paragraph" variant would amortize
  the backscan; not yet tried.

- **Cursor-migrating-upward edits.** The `insert` perftest does
  `insert + back_char + back_line` each iteration, drifting the
  cursor up through never-edited territory. `Layout.note_change`'s
  cols-margin truncation drops every ladder entry below the cursor
  each step (they're all on the just-split piece's `post`, shifted
  by `+1` from the insert, and within `cols` of the edit). The
  ladder oscillates between ~25 entries (after paint extends) and
  ~3 (after note_change truncates) — recenter rate ≈ 50%. Not a
  bug — this is the documented `cols`-margin behavior — but the
  perftest's cursor pattern is somewhat pathological for the
  design. Normal interactive editing (cursor stays put while
  typing) wouldn't trigger this.

- **`(P, offset) → (pre, offset)` remap.** Implemented (see
  *Validity / Remap*). The doc's earlier note "unclear whether the
  added complexity is justified" turned out to be wrong: without it,
  `Layout.note_change` wipes the ladder on every keystroke for a
  freshly-opened document, dropping `insert` perf by ~30%.

- **Duplicate `format_line()` per vertical move (open, not fixed).**
  Splitting "land the point on the goal column" (`Layout._vertical_move`,
  command time) from "locate the point for the cursor cell"
  (`Display.paint` → `Layout.locate` → `column_at`, paint time) means
  both now call `format_line()` on the same destination line every
  vertical move — the pre-cleanup renderer did this once, folding the
  deferred `pin_preferred_col` fixup into the same emit-free render that
  found the cursor cell. Costs `up_from_end` ~13% (see
  `docs/plans/perf-baseline.md`'s "MVC cleanup" entry for the profiling
  evidence). A fix would need `Layout` to remember the `col_map` (or
  just the resulting screen column) it just computed for the current
  vertical-move destination and let `locate` reuse it when the queried
  location matches `last_vertical_dest` — deliberately not attempted
  here since it means reopening the Task 1/2 ownership split rather than
  a docs change.
