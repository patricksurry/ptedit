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

## Expanded baseline (May 2026, branch `ladder-preserve-top`)

Two new scenarios added: a `delete` mirror of `insert`, and a `soak`
that drives the existing `random_soak` action stream (4 MOVE : 2
INSERT : 2 DELETE : 2 REPLACE) with `paint()` between actions —
closer to a realistic edit mix than any single-loop scenario.

Captured at the head of `ladder-preserve-top` *before* implementing
preserve-prefix (full-invalidation still in place). Numbers shifted
slightly from the table above because piece equality is now
identity-based (auto dataclass `__eq__` was recursing chains and
blowing the stack on soak — fixed in this branch).

| scenario       | fps  |
|----------------|------|
| insert         | 152  |
| delete         | 179  |
| up_from_end    | 492  |
| pgup_from_end  | 211  |
| pgdn_from_top  | 342  |
| soak           | 394  |

## Preserve-prefix experiment (May 2026, branch `ladder-preserve-top`, discarded)

Tried preserving a prefix of the BoL ladder across edits instead of
the unconditional invalidation.  Two variants:

1. *ladder[0] only, with '\\n'-within-cols safety check*: the check
   never fired on Alice because most cached BoLs are wrap fragments
   of long paragraphs, not real line ends.  No measurable speedup.

2. *Walk ladder, keep `bols[i]` iff `bols[i]` and `bols[i+1]` are both
   in untouched pieces*: cheap O(ladder_length) check per edit, fired
   often.  Required also relaxing `bol_to_prev_bol`'s "pt is at
   `ladder[len-2]`" assertion (it assumed the cache was always
   freshly built around pt).

| scenario       | invalidate | preserve | ratio |
|----------------|------------|----------|-------|
| insert         | 152        | 161      | 106%  |
| delete         | 179        | 184      | 103%  |
| up_from_end    | 492        | 437      |  89%  |
| pgup_from_end  | 211        | 206      |  98%  |
| pgdn_from_top  | 342        | 274      |  80%  |
| soak           | 394        | 108      |  27%  |

Edit scenarios get a small bump, navigation scenarios regress, and
the realistic-mix `soak` scenario regresses ~70%.  The relaxed
`bol_to_prev_bol` lookup (an extra `index()` call per call instead
of computing the index from `len`) accounts for most of the
navigation regression; `soak` adds the per-edit walk cost on top.

Decision: revert.  The preserve-prefix idea has surface appeal but
the savings (one backward scan per ladder rebuild) don't dominate
the costs once you account for the bookkeeping and the relaxed
hot-path assumption in `bol_to_prev_bol`.

Two unrelated bugs surfaced and were kept:
- `Piece.__eq__` was the auto-generated dataclass equality, which
  recursively compared `prev`/`next` and blew the stack on long
  chains (only triggered by soak's deep edits).  Fixed by
  `eq=False`; pieces now compare by object identity.
- `Display.find_top` left `fallback` unbound when `preferred_row`
  was unreachable (small `rows`, e.g. tests).  Initialize before
  the loop.
