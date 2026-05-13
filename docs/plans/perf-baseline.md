# Perftest baseline

Captured against `tests/alice1flow.asc`, BoL ladder enabled, on branch `python-cleanup` at commit 0895cf34f9663fd571c177843a7e359aef2825e1.

| scenario       | fps  |
|----------------|------|
| insert         | 229  |
| up_from_end    | 491  |
| pgup_from_end  | 212  |
| pgdn_from_top  | 329  |

## Task 14 spike: no ladder, on-demand reflow

Branch `experiment/no-ladder` at commit 975f476 (later discarded).

| scenario       | baseline fps | no-ladder fps | ratio |
|----------------|--------------|---------------|-------|
| insert         | 229          | 58            | 25%   |
| up_from_end    | 491          | 205           | 42%   |
| pgup_from_end  | 212          | 41            | 19%   |
| pgdn_from_top  | 329          | 67            | 20%   |

(ratio = no-ladder / baseline; >100% means faster, <100% means slower)

**Decision (outcome C per Task 14 plan):** the BoL ladder is doing real
work across every scenario, including paint-heavy `insert` (frame paints
walk many display lines forward and benefit from cached BoLs from prior
frames). Discarded `experiment/no-ladder`, kept the ladder. Proceed to
Task 15 (simplify `rescue_ladder` by full invalidation) and skip Task
16 (per-piece nl_count is dwarfed by ladder cost).

## Task 15: full invalidation instead of rescue_ladder

| scenario       | baseline fps | invalidate fps | ratio |
|----------------|--------------|----------------|-------|
| insert         | 229          | 143            | 62%   |
| up_from_end    | 491          | 490            | 100%  |
| pgup_from_end  | 212          | 211            | 100%  |
| pgdn_from_top  | 329          | 326            | 99%   |

Only `insert` regresses (each keystroke invalidates the cache, next
paint rebuilds). 143 fps is still well above human-noticeable for
typing latency, and the simplification removes ~50 lines of subtle
position-arithmetic code in `rescue_ladder`. Kept.

## Pre-rewrite reference (rendering-redesign branch)

Captured at HEAD of `rendering-redesign` (commit `642472f`)
against `tests/alice1flow.asc`, prior to Stage 1 of the ladder redesign.

*Re-captured under mock `Screen` path (no curses I/O); previous `script`-style numbers replaced.*

| scenario       | fps  |
|----------------|------|
| insert         | 150  |
| up_from_end    | 525  |
| pgup_from_end  | 218  |
| pgdn_from_top  | 346  |

## Stage 1 — naive baseline (rendering redesign)

No ladder; every frame backscans from the cursor and reformats. Captured
at commit `4dfae5d` against `tests/alice1flow.asc` under the mock-Screen
perftest path.

| scenario       | pre-rewrite fps | naive fps | ratio |
|----------------|-----------------|-----------|-------|
| insert         | 150             | 101       | 67%   |
| up_from_end    | 525             | 122       | 23%   |
| pgup_from_end  | 218             | 57        | 26%   |
| pgdn_from_top  | 346             | 122       | 35%   |

Severe regression expected — this is the floor against which Stage 2 is
measured.

## Stage 2 — new ladder (rendering redesign)

`[first, top, last)` ladder per `docs/rendering.md`: edit-time truncation,
Phase 1 cursor location (bracket / extend / re-anchor), sticky top with
guard-zone scrolling, and the four Phase 2 redraw cases (full / scroll /
local-edit tail render / no-scroll skip). Captured at commit `d97aa48`
against `tests/alice1flow.asc` under the mock-Screen perftest path.

| scenario       | pre-rewrite fps | naive fps | new fps | new vs pre-rewrite | new vs naive |
|----------------|-----------------|-----------|---------|--------------------|--------------|
| insert         | 150             | 101       | 154     | 103%               | 1.5×         |
| up_from_end    | 525             | 122       | 1121    | 214%               | 9.2×         |
| pgup_from_end  | 218             | 57        | 181     | 83%                | 3.2×         |
| pgdn_from_top  | 346             | 122       | 209     | 60%                | 1.7×         |

Common interactive operations win big: `up_from_end` (line-by-line cursor
movement on a stable window) is the `no_scroll` fast path → zero screen
writes, 9× faster than naive and 2× faster than pre-rewrite. `insert`
(type + back-char + back-line each iteration) is `local_edit` + `no_scroll`
→ marginally above pre-rewrite.

`pgup_from_end` / `pgdn_from_top` are below pre-rewrite. Page scrolls move
the cursor a full screen, which always changes `top` → the `full` redraw
case. Our `full` redraw re-formats every visible line from scratch via
`format_line`; the pre-rewrite renderer reused cached BoL marks during the
render. A known follow-up: have `_render_rows` consult / extend the ladder
as it formats (instead of `find_top` doing a separate `_extend_lines` pass
the render then ignores) so `full`/`scroll` reuse cached work. Left out of
this milestone — the implementation is faithful to `docs/rendering.md`'s
*structure*; this is a pure optimization within the `full` case.

### Stage 2 + recenter optimization

`find_top`'s recenter no longer calls `_set_window` (which `reset()`s the
ladder and re-formats from a hard BoL); after the `bol_to_prev_bol` walk
the new top is already a ladder entry, so we just re-index. A fallback to
`_set_window` is kept for the degenerate single-entry case in
`bol_to_prev_bol` where the point may not be on a ladder entry. Captured at
this commit (see git log).

| scenario       | pre-rewrite | new (pre-opt) | new (+recenter opt) |
|----------------|-------------|---------------|---------------------|
| insert         | 150         | 154           | 181                 |
| up_from_end    | 525         | 1121          | 1181                |
| pgup_from_end  | 218         | 181           | 197                 |
| pgdn_from_top  | 346         | 209           | 257                 |

### Stage 2 + render-extends-ladder optimization

`Display._render_rows` now extends the ladder as it formats each line
(appending the next BoL when not already cached). This lets `find_top`
drop the eager `_extend_lines` pass and the overflow-defense `chosen_pos`
re-find. `_set_window` (recenter fallback) is replaced by `_reanchor` —
the forward-extend half is now `_render_rows`'s job. Net: ~40 lines off,
single formatting pass over the visible window per frame.

| scenario       | pre-rewrite | new (+recenter) | new (+render-extends) |
|----------------|-------------|-----------------|-----------------------|
| insert         | 150         | 181             | 267                   |
| up_from_end    | 525         | 1181            | 1304                  |
| pgup_from_end  | 218         | 197             | 247                   |
| pgdn_from_top  | 346         | 257             | 316                   |
