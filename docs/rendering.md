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
len(slots)`; `top` is a plain integer index. The algorithm is
identical to the Forth contract; the data-structure mechanics
diverge for Python ergonomics.

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

| Case | Condition | Work |
|------|-----------|------|
| **Full redraw** | `top` value changed (anchor lost, large jump, or scroll) | Re-render every row from the new `top` anchor. |
| **Local edit**  | `top` unchanged, but `last < top + rows` | Source text changed on screen. Re-render rows `[K, rows)` where `K = last - top`; rows above are byte-stable in the video buffer. |
| **No scroll**   | `top` unchanged, ladder still covers the window, no edit | Data on screen is valid. If no active selection, emit zero cells (cursor cell handled by the caller). If a selection is active, fall back to Full redraw — cell-granular attribute deltas are a 6502 concern. |

Python folds the doc's "Scroll" sub-case into Full redraw: terminal
block-copy is out of scope, and the cached ladder primes `format_line`
either way. A Forth/6502 port should distinguish them to exploit
video-RAM block moves.

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
`top_loc` (a `Location` that gets remapped through edits via the
same `edit.remap_location`). On the next frame:

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
  chars. Tried (`rows * cols / 2` threshold). **Two findings:**

    1. **Perf regression**, not improvement: `insert` -24%,
       `up_from_end` -21%. Each reanchor's cost grew ~5× (one
       backscan per paragraph crossed, plus more `format_line`
       calls forward) and the rare-cascade-during-recenter benefit
       didn't compensate. The dominant `insert` cost is
       `change_handler` truncating below the cursor each step, not
       reanchor itself.

    2. **Latent contract violation revealed.** `bol_to_prev_bol`'s
       fallback walks `move_point(-1)` + `reanchor(cursor-1)` +
       `set_point(lad[-2])`. With *shallow* reanchor the cursor-1
       case "at a `\n` preceded by a `\n`" (consecutive newlines /
       empty line) produces a single-entry ladder; `len(lad) < 2`
       skips the `set_point`; cursor stays at `cursor-1` (the empty
       line's BoL) — *correct*. With *deep* reanchor the same case
       produces a multi-entry ladder; the `set_point(lad[-2])`
       fires and lands at the line *before* the empty line —
       *wrong*. The empty line's BoL is never re-emitted because
       `reanchor`'s forward-format loop condition `point < cursor`
       exits exactly when `point == cursor-1`. The fix would be a
       loop condition that consumes one more `format_line` when
       `point == cursor`, but that risks an infinite loop at doc
       end; ought to be worked out carefully if we revisit this.

   Net: shallow `reanchor` stays. The contract between `reanchor`
   and `bol_to_prev_bol`'s fallback is implicit ("reanchor produces
   a single-entry ladder iff cursor is already at a hard BoL whose
   previous char is also `\n`") and should be made explicit before
   any change to either side.

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
  cursor up through never-edited territory. `change_handler`'s
  cols-margin truncation drops every ladder entry below the cursor
  each step (they're all on the just-split piece's `post`, shifted
  by `+1` from the insert, and within `cols` of the edit). The
  ladder oscillates between ~25 entries (after paint extends) and
  ~3 (after change_handler truncates) — recenter rate ≈ 50%. Not a
  bug — this is the documented `cols`-margin behavior — but the
  perftest's cursor pattern is somewhat pathological for the
  design. Normal interactive editing (cursor stays put while
  typing) wouldn't trigger this.

- **`(P, offset) → (pre, offset)` remap.** Implemented (see
  *Validity / Remap*). The doc's earlier note "unclear whether the
  added complexity is justified" turned out to be wrong: without it,
  `change_handler` wipes the ladder on every keystroke for a
  freshly-opened document, dropping `insert` perf by ~30%.
