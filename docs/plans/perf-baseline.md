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
