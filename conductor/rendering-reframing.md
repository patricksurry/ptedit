# Rendering Reframing Plan

## Objective
Rewrite `docs/rendering.md` to simplify the conceptual model for screen updates. We will replace the artificial "L0-L3" update levels with a unified state machine driven by three simple ring-buffer indices: `first`, `top`, and `last`. We will also document the 6502-specific memory layout for the ladder (64 slots, 256 bytes) that allows fast index-based lookups.

## Key Files & Context
- `docs/rendering.md`: The primary target for the rewrite.

## Proposed Changes

### 1. Replace "Update levels" with "Ladder State"
Remove the L0, L1, L2, and L3 classifications. Introduce the three indices that govern the ring buffer:
- `first`: The index of the oldest valid line anchor (highest up in the document).
- `top`: The index of the line anchor currently displayed at screen row 0.
- `last`: The index *one past* the newest valid line anchor (lowest down in the document).

When `first == last`, the ladder is empty (invalid). The visible screen occupies indices from `top` to `top + rows - 1` (modulo the ring size).

### 2. Document the 6502 Ring Buffer Implementation
Add a section detailing the target 6502 implementation:
- The ladder uses exactly 64 slots ($2^6$), meaning indices wrap naturally using a bitwise mask `idx & $3F`.
- Each `Location` is 4 bytes (2-byte piece pointer, 2-byte offset).
- To avoid expensive multiplication and pointer arithmetic, the 256 bytes of ladder state are stored as four page-aligned, parallel 64-byte arrays (e.g., `rung_piece_lo`, `rung_piece_hi`, `rung_off_lo`, `rung_off_hi`).
- This layout allows accessing any component of a ladder location using a single 8-bit index register (X or Y).

### 3. Redefine the Rendering Cycle in Two Phases
Structure the update process around how the indices change:

**Phase 1: Update Ladder**
- **On Edit:** Walk the ladder from `first` up to `last`. The first entry that fails the validity check (data-stale or wrap-stale) becomes the new `last`, effectively truncating the ladder backward.
- **On Cursor Move:** The renderer formats forward from `last` to ensure the ladder brackets the cursor. If the cursor moves outside the visible window (the `rows` entries starting at `top`), we shift `top` forward or backward (Scroll). If `top` moves out of the `[first, last)` bounds, it triggers an anchor rescue.

**Phase 2: Determine Redraw**
Determine what to paint based on the state of the ladder relative to the screen:
- **`top` changed:** 
  - *Scroll:* If `top` shifted but is still valid (`first <= new_top < last`), block-copy the overlapping screen rows and render only the newly exposed rows at the top or bottom using the ladder.
  - *Lost Anchor:* If the new `top` is outside the valid ladder (or the ladder was entirely truncated such that `first == last`), walk backward from the cursor to establish a new `top`, then perform a full redraw.
- **`top` unchanged, but `last < top + rows`:** The ladder was truncated *within* the visible screen due to an edit. Retain the screen rows up to `last - top`, and redraw from that row downwards.
- **`top` unchanged, and `last >= top + rows`:** The entire visible screen remains valid. Only the cursor or mark moved. Just update the cursor position and invert cell highlights (no character data changes).

## Verification
- Review the rewritten `docs/rendering.md` to ensure the new state machine logic accurately replaces the old L0-L3 framework.
- Ensure the edge cases (like an edit at the top of the screen that truncates the whole visible ladder) organically result in the correct redraw behavior.
