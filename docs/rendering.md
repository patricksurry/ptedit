# Efficient Rendering

On vintage hardware even repainting an 80 × 24 screen is expensive.
This document describes how we update that screen efficiently.

Drawing each `rows × cols` frame from the piece table requires:

1. Picking a top-of-screen anchor — the beginning-of-line (BoL) 
   for the first screen row.
2. Walking forward from the anchor, formatting `rows` visual lines:
   tabs, escapes for non-printables, soft-wrap at `cols`.
3. Drawing the cursor at the document point and highlight the region
   between point and mark (if any).

With no other context, finding the top-of-screen anchor requires a
backward scan to the nearest line break and then a forward walk of
the off-screen rows up to the point.  The backward scan is
unbounded in the worst case (a long unwrapped paragraph with no
`\n`); the forward render is bounded by `rows × cols`.  We want to
amortize both across consecutive frames.

## Constraints

On vintage hardware both memory and cycles are extremely limited.
The renderer should:

- Use a memory-mapped video buffer as the only copy of displayed
  bytes (beyond the piece table itself).  Updating a cell is one
  byte write to the buffer.
- Keep state minimal — no shadow screen buffer or other large
  duplicates of document data.
- Use no dynamic allocation.

## Ladder State

The renderer maintains a **ladder** of BoL marks — one per visual
line on or near the screen. The ladder is stored in a ring buffer
controlled by three indices:

- `first`: Index of the first valid line anchor (nearest document start).
- `top`: Index of the line anchor displayed at screen row 0.
- `last`: Index of the first empty slot (one past the line anchor nearest document end).

The ladder spans `[first, last)` (half-open). It is empty when
`first == last`. The visible region corresponds to the `rows`
entries starting at `top` (modulo ring size).

The ladder typically extends past the visible window in both
directions. *Above* `top` because re-anchoring lands on the nearest
newline before the screen, so those rungs come along for free.
*Below* `top + rows` because scrolling and edits often leave
already-formatted rungs we can preserve rather than discard.

On the 6502, each `Location` is a 2-byte piece pointer plus a 2-byte
offset. For simpler indexing, a 64 slot ladder ($2^6$) takes exactly
256 bytes.

## Rendering Cycle

Each frame update follows a two-phase process.

### Phase 1: Update Ladder

In what follows, the cursor's *position* means its document position;
comparisons against ladder slots are against the document position
stored at that slot (`ladder[i].pos`).

1. **If a document edit occurred:** Walk `[first, last)` and truncate
   at the first invalid entry (see *Validity* below) — set `last` to
   that index. The cursor may or may not still be bracketed
   afterward; the next step handles both cases uniformly.

2. **Locate the cursor relative to the ladder.** With at most 64
   rungs, a linear scan finds which (if any) ladder line contains the
   cursor. Three cases:

   - **Bracketed** (some `i ∈ [first, last)` has `ladder[i].pos ≤
     cursor < ladder[i+1].pos`, treating `ladder[last].pos` as +∞):
     cursor is within the cached range. If the containing line falls
     in the visible-window guard zone, shift `top` (Scroll). Otherwise
     no ladder change.

   - **Just past `last`** (cursor at most `rows` lines beyond the last
     cached BoL): format forward from `last` to extend the ladder
     (Extension). The threshold is `rows` because extending further
     costs more than a full redraw from a fresh anchor.

   - **Otherwise** (cursor before `first`, large forward jump, or
     truncation orphaned the cursor): **Re-anchor.** Scan newlines
     backward from the cursor to find a new `top`; reset to a fresh
     ladder rooted there.

A pure selection change (mark moves, point does not, no edit) skips
Phase 1 entirely.

### Phase 2: Screen Update

The relationship between the indices after Phase 1 determines the redraw 
strategy.

| Case | Condition | Work |
|------|-----------|------|
| **Local move, no scroll** | `top` unchanged AND `last >= top + rows` | No document edit (move only). Data is valid for all rows; update only cursor/highlight cells (attribute flips). |
| **Local move with scroll** | `top` index changed, but new `top` is within `[first, last)` | Visible content shifted. Block-copy overlapping rows (or just reformat); render new rows as needed. |
| **Local edit** | `top` unchanged, but `last < top + rows` | Source text changed on screen. Re-render screen from end of ladder, extending `last` downwards. |
| **Full redraw** | `top` value changed (anchor lost or large jump) | Environment changed. Re-render every row from the new `top` anchor. |

A selection-only change is a degenerate "local move, no scroll":
flip attributes on cells whose membership in the highlighted region
changed, leave the rest untouched.

## Validity

Validity checks are only required when a document **edit** occurs. For 
cursor moves, we only need to verify the cursor is bracketed by 
the existing ladder.

A ladder entry `(piece, offset)` is **safe to keep** iff:

1. `piece` is **not** in the unlinked set (recorded by the `Edit`).
2. The entry is more than `cols` chars before the edit start.

Truncating at the first invalid entry is simpler than per-entry
rescue and is correct by construction.

The `cols` margin accounts for soft-wrap propagation: an edit on
visual line 2 can change the wrap point of visual line 1 if a word
is "pulled" up or "pushed" down. This is a critical edge case for
any implementation. Forward propagation needs no separate handling
— every entry from the edit onwards is truncated regardless.

#### Example: Wrap Propagation

```
cols = 20
before:  "some short words supercalifragilistic..."
                          ^pos 17 (BoL of visual line 2)
                          line 1 = "some short words "      (wrap after space)
                          line 2 = "supercalifragilistic"   (no wrap)

edit:    insert ' ' after "super" (pos 22)

after:   "some short words super califragilistic..."
                                 ^new wrap point at pos 23
                          line 1 = "some short words super "  (absorbed "super ")
                          line 2 = "califragilistic..."
```

The edit at pos 22 changed the BoL of visual line 2 (from 17 to 23). 
Any ladder entry within `cols` of the edit is discarded.

## Alternatives considered

- **Per-piece newline counts.**  Enables fast "what line is point 
  on?" via piece-chain walk. Useful for status-bar line numbers, 
  but the ladder already provides the structure needed for the 
  visible region.
- **Per-entry cache rescue.** A previous implementation walked
  position arithmetic to reconstruct each cached BoL in the new
  piece chain after every edit (~50 lines, several edge cases).
  Removed in favor of full invalidation; insert FPS dropped 229 →
  143, still well above any human-noticeable threshold.
- **`(P, offset) → (pre, offset)` remap.** When an edit splits a
  single piece `P` into `pre / edit / post`, every ladder entry
  with `offset < len(pre) - cols` could be cheaply remapped to
  `(pre, offset)` and kept. This specifically rescues the
  freshly-opened, single-piece case where the first edit otherwise
  invalidates the entire ladder. Possible future extension; unclear
  whether the added complexity is justified given how quickly the
  piece chain fragments in practice — left out of MVP.
