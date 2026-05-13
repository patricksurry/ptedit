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

### Stage 2 + simplification refactor (final)

Bundled clarity refactor: dropped `_locate_cursor_cell` (replaced by an
`emit=False` flag on `_render_rows`); `find_top` returns a `recentered`
bool so `paint` no longer reverse-engineers it from a `prev_top_pos`
delta; inlined `_locate_cursor` into `ensure_bracketed`; renamed
`_ensure_bracketed`/`_find_line_index`/`_reanchor` public (they're used
by `Display`); replaced `last_truncate_top: int | None` with a
`last_truncate_invalidated_top: bool` flag; deleted dead `row_positions`
state and a stray debug `logging.info` in `_render_rows`' hot loop.

| scenario       | pre-rewrite | new (+render-extends) | new (+refactor)  |
|----------------|-------------|-----------------------|------------------|
| insert         | 150         | 267                   | **304**          |
| up_from_end    | 525         | 1304                  | **3358**         |
| pgup_from_end  | 218         | 247                   | **250**          |
| pgdn_from_top  | 346         | 316                   | **335**          |

The `up_from_end` 2.5× jump is almost certainly the deleted hot-loop
`logging.info`: it builds the f-string (and calls `doc.at_end()`) on
every row of every render, even when the level filters the message
away. With ~3000 paints/sec × 23 rows ≈ 70 000 spurious format calls
per second of the perftest, removing it was a real drag-removal, not
just hygiene.

### Stage 2 + PR-review refactor

Followed up with PR-review feedback (commit `89b4d26`): introduced a
`Cell` NamedTuple in place of `tuple[int, int]`; replaced `top_pos: int`
with `top_loc: Location`; rewrote the guard-zone scroll math as a clamp;
**fixed the sticky-top scroll bug** where `find_top` returned "did I take
the recenter branch" instead of "did `top` change", causing the
no-scroll path to fire (zero puts) when a guard-zone scroll had moved
`top`; inlined the four-case classifier; switched `Ladder` to a
`collections.deque` subclass per the doc's spec; simplified the
unlinked-pieces watcher signature from `frozenset[int]` to
`tuple[Piece, Piece] | None`. Plus a typing pass (`78f7305`) and
regression tests + coverage tooling (`4e21a39`).

The `deque` switch costs perf at the line-nav hot path: Python's
`deque[i]` is O(n) where `list[i]` is O(1), and `bol_to_prev_bol`
indexes the ladder once per call.

| scenario       | pre-refactor (`daee614`) | post-refactor (`4e21a39`) |
|----------------|--------------------------|---------------------------|
| insert         | 304                      | 252                       |
| up_from_end    | 3358                     | 1428                      |
| pgup_from_end  | 250                      | 257                       |
| pgdn_from_top  | 335                      | 332                       |

Page scrolls and `insert` are largely unchanged; `up_from_end` is where
the deque indexing hurts. Trading semantic clarity (deque is the doc's
ring-buffer analogue) for ~57% on the line-nav perftest. A list-backed
`Ladder` with an explicit MAX cap would recover the speed.

### Summary vs pre-rewrite

| scenario       | pre-rewrite | naive | final | final / pre-rewrite |
|----------------|-------------|-------|-------|---------------------|
| insert         | 150         | 101   | 252   | **1.7×**            |
| up_from_end    | 525         | 122   | 1428  | **2.7×**            |
| pgup_from_end  | 218         | 57    | 257   | 118%                |
| pgdn_from_top  | 346         | 122   | 332   | 96%                 |

Common interactive ops (line nav, typing) are faster. Page scrolls
land within noise of pre-rewrite — they're full redraws in both
implementations, and the ladder primes `format_line` similarly in each.

File sizes:

| file                    | pre-rewrite | final | delta |
|-------------------------|-------------|-------|-------|
| `src/ptedit/layout.py`  | 274         | 342   | +68   |
| `src/ptedit/display.py` | 162         | 278   | +116  |

The growth is the doc's design surface: `Ladder` + Phase 1 (`reanchor`,
`ensure_bracketed`, `_extend_to`, `line_index`) in Layout; sticky top
with guard-zone scrolling and the four Phase 2 redraw cases (full /
scroll / local-edit tail / no-scroll skip) in Display.
