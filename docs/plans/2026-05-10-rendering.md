# Ladder-Based Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc `Ladder` deque in `src/ptedit/layout.py` with the explicit `[first, top, last)` ring-buffer ladder specified in `docs/rendering.md`, in two stages — naive baseline first, optimized ladder second — with perf measured at each stage.

**Architecture:** Two-stage rewrite on the `rendering-redesign` branch.
- **Stage 1 (Naive Baseline):** Strip out all ladder code from `Layout`. `find_top` becomes a backscan from the cursor on every frame; `paint` does a full redraw every frame; `change_handler` is a no-op. Working but slow editor; provides a measured floor.
- **Stage 2 (New Ladder):** Reintroduce caching as the ladder of `docs/rendering.md` (`first/top/last` semantics, half-open `[first, last)`, edit-truncate validity, three-case Phase 1 cursor location, four-case Phase 2 redraw strategy).

**Goal of the Python implementation:** a *simple, illustrative* reference that will guide an eventual 6502/Forth port. KISS, DRY, SOLID. The 6502 port will use a true 64-slot ring buffer with modular index arithmetic (per the byte-budget constraint in `docs/rendering.md`); the Python implementation uses a plain `list[Location]` with `first == 0`, `last == len(slots)`, and `top` as a simple integer index. This is intentional divergence — the *algorithm* is what's portable, not the data structure mechanics. Document this in the `Ladder` docstring so the Forth port author has a clear pointer back to the spec.

The naive code from Stage 1 is **not** kept in the running tree; it lives only in git history as a perf datapoint. A golden screen-buffer test, captured against the *current* code before any changes and unchanged across both stages, serves as the correctness oracle.

**Tech Stack:** Python 3.12, pytest, no curses (uses the abstract `Screen` base class for testing). `pyright` for type checking. `uv` for dependency management. Existing perftest harness (`python -m ptedit -P <scenario>`).

---

## File Structure

Files modified or created across both stages:

| File | Stage 1 | Stage 2 |
|------|---------|---------|
| `src/ptedit/layout.py` (274 LoC) | Strip ladder; replace BoL primitives with backscan/forward-walk | Add new list-based `Ladder` class; wire into Phase 1/Phase 2 cycle |
| `src/ptedit/display.py` (162 LoC) | `find_top` becomes a backscan from cursor; `paint` always full-redraws | `paint` implements Phase 2 case dispatch (start with full-redraw only, optimize incrementally) |
| `tests/test_layout.py` | Adjust assertions where API drops (`bol_ladder`, `ladder_point`) | Add Ladder unit tests; restore higher-level coverage |
| `tests/test_display.py` | Adjust internal-state pokes if any break | No change expected |
| `tests/test_render_golden.py` (NEW) | Create — captures painted screen bytes as fixture; pinned across both stages | No change |
| `tests/golden/*.bin` (NEW) | Fixture captures of expected screen bytes | No change |
| `docs/plans/perf-baseline.md` | Append naive baseline numbers | Append new ladder numbers |

The golden test is the load-bearing correctness check. It captures observable `paint()` byte output for known navigation/edit sequences against `tests/alice1flow.asc`. The same fixtures must pass at the end of every Stage 1 and Stage 2 task.

---

## Stage 1 — Naive Baseline

### Task 1.1: Capture current perf as the "before" line

**Files:**
- Modify: `docs/plans/perf-baseline.md`

- [ ] **Step 1: Run all four perftest scenarios on current code**

```bash
for s in insert up_from_end pgup_from_end pgdn_from_top; do
    echo -n "$s: "; uv run python -m ptedit -P $s tests/alice1flow.asc
done
```

Expected: four lines like `insert: NNN frames in 1.00s = NNN fps`.

- [ ] **Step 2: Append a "Pre-rewrite (rendering-redesign branch)" section to `docs/plans/perf-baseline.md`**

Add at the end of the file:

```markdown
## Pre-rewrite reference (rendering-redesign branch)

Captured at HEAD of `rendering-redesign` (commit `<git rev-parse HEAD>`)
against `tests/alice1flow.asc`, prior to Stage 1 of the ladder redesign.

| scenario       | fps  |
|----------------|------|
| insert         | <N>  |
| up_from_end    | <N>  |
| pgup_from_end  | <N>  |
| pgdn_from_top  | <N>  |
```

Fill the `<N>` values with measurements from Step 1; replace `<git rev-parse HEAD>` with the actual short SHA.

- [ ] **Step 3: Commit**

```bash
git add docs/plans/perf-baseline.md
git commit -m "perf: record pre-rewrite baseline on rendering-redesign branch"
```

---

### Task 1.2: Add golden-buffer correctness test

**Files:**
- Create: `tests/test_render_golden.py`
- Create: `tests/golden/.gitkeep`

The golden test captures `Screen.put` output as a sequence of `(ch, highlight)` tuples for deterministic navigation+edit scripts. It runs first against current code (capturing fixtures), then unchanged across both rewrites.

- [ ] **Step 1: Create a recording `Screen` subclass and the test scaffolding**

Create `tests/test_render_golden.py`:

```python
import os
from pathlib import Path

from ptedit import display, document
from ptedit.screen import Screen


GOLDEN_DIR = Path(__file__).parent / 'golden'
ALICE_FLOW = (Path(__file__).parent / 'alice1flow.asc').read_text()
UPDATE = os.environ.get('UPDATE_GOLDENS') == '1'


class RecordingScreen(Screen):
    """Captures every put() as (ch, highlight) for byte-level golden comparison."""
    def __init__(self, height: int, width: int):
        super().__init__(height, width)
        self.events: list[tuple[int, bool]] = []

    def put(self, ch: int, highlight: bool = False):
        self.events.append((ch, highlight))

    def encode(self) -> bytes:
        # Two bytes per cell: char, then highlight flag (0/1).
        out = bytearray()
        for ch, hi in self.events:
            out.append(ch & 0xff)
            out.append(1 if hi else 0)
        return bytes(out)


def assert_golden(name: str, payload: bytes):
    path = GOLDEN_DIR / f'{name}.bin'
    if UPDATE or not path.exists():
        path.write_bytes(payload)
        return
    expected = path.read_bytes()
    assert payload == expected, (
        f'golden {name} mismatch: got {len(payload)} bytes, '
        f'expected {len(expected)} bytes; '
        f"re-run with UPDATE_GOLDENS=1 to refresh"
    )


def _make_display() -> tuple[display.Display, document.Document, RecordingScreen]:
    doc = document.Document(ALICE_FLOW)
    scr = RecordingScreen(24, 80)
    dpy = display.Display(doc, scr)
    return dpy, doc, scr


def test_golden_open_paint():
    """Initial paint at start of doc."""
    dpy, doc, scr = _make_display()
    dpy.paint()
    assert_golden('open_paint', scr.encode())


def test_golden_pgdn_pgup():
    """Page down twice, page up twice."""
    dpy, doc, scr = _make_display()
    dpy.paint()
    for _ in range(2):
        dpy.layout.move_forward_page()
        dpy.paint()
    for _ in range(2):
        dpy.layout.move_backward_page()
        dpy.paint()
    assert_golden('pgdn_pgup', scr.encode())


def test_golden_insert_typing():
    """Type 'hello' at start, redrawing after each keystroke."""
    dpy, doc, scr = _make_display()
    dpy.paint()
    for ch in b'hello':
        doc.insert(ch)
        dpy.paint()
    assert_golden('insert_typing', scr.encode())


def test_golden_end_to_top():
    """Navigate to end, then page up several times."""
    dpy, doc, scr = _make_display()
    doc.set_point_end()
    dpy.paint()
    for _ in range(5):
        dpy.layout.move_backward_page()
        dpy.paint()
    assert_golden('end_to_top', scr.encode())
```

Note: if `Document.insert` is not the correct API, substitute the existing edit method (check `src/ptedit/document.py` and `src/ptedit/edit.py`). The point is to drive the same script through the renderer in three different implementations.

- [ ] **Step 2: Create the goldens directory marker**

```bash
mkdir -p tests/golden
touch tests/golden/.gitkeep
```

- [ ] **Step 3: Generate the goldens against current code**

```bash
UPDATE_GOLDENS=1 uv run pytest tests/test_render_golden.py -v
```

Expected: 4 PASS, 4 `.bin` files written under `tests/golden/`.

- [ ] **Step 4: Re-run without UPDATE flag to verify they pin**

```bash
uv run pytest tests/test_render_golden.py -v
```

Expected: 4 PASS, no fixture writes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_render_golden.py tests/golden/
git commit -m "test: golden screen-buffer fixtures pinning current renderer behavior"
```

---

### Task 1.3: Strip the ladder from `Layout`

**Files:**
- Modify: `src/ptedit/layout.py`
- Modify: `tests/test_layout.py`

This task removes the `Ladder` class, the `bol_ladder` field, `ladder_point`, and the `change_handler` invalidation. BoL navigation primitives become straight document walks with no caching.

- [ ] **Step 1: Replace `Layout.__init__` and remove the `Ladder` class**

In `src/ptedit/layout.py`, delete the entire `Ladder` class (lines 11–23 of the current file) and the `from collections import deque` import. Replace the `Layout.__init__` body to drop the `bol_ladder` field:

```python
class Layout:
    def __init__(self, doc: Document, cols: int, rows: int, rungs: int, tab: int = 4):
        self.doc = doc

        assert (cols // tab) * tab == cols, "tab should divide cols"

        self.cols = cols
        self.rows = rows
        self.rungs = rungs           # retained for API compat; unused in naive renderer
        self.tab = tab

        self.preferred_col = 0
        self.pin_preferred_col = False
```

- [ ] **Step 2: Replace `change_handler` with a no-op**

```python
    def change_handler(self, start: Location, end: Location):
        # Naive renderer keeps no cache; nothing to invalidate.
        pass
```

- [ ] **Step 3: Rewrite `clamp_to_bol` as a backscan**

```python
    def clamp_to_bol(self):
        """Move point to the BoL of the visual line currently containing it."""
        if self.doc.at_start():
            return
        # Walk back to nearest hard newline (or doc start).
        pt = self.doc.get_point()
        self.doc.move_point(-1)
        self.doc.find_char_backward('\n')
        # If we stopped on a '\n', step past it.
        if not self.doc.at_start() and self.doc.get_char() == '\n':
            self.doc.move_point(1)
        hard_bol = self.doc.get_point()
        # Walk forward formatting visual lines until the next BoL is past pt.
        while self.doc.get_point().is_strictly_before(pt):
            prev_bol = self.doc.get_point()
            self.format_line()  # advances point to next visual BoL
            if self.doc.get_point().is_at_or_after(pt):
                self.doc.set_point(prev_bol)
                return
        # Already at hard BoL.
        self.doc.set_point(hard_bol)
```

Verify against `Document` API: confirm `find_char_backward`, `get_char`, `is_strictly_before`, `is_at_or_after` exist with these signatures by greping `src/ptedit/document.py` and `src/ptedit/location.py`. Adjust signatures if names differ.

- [ ] **Step 4: Rewrite `bol_to_next_bol` to call `format_line` directly**

```python
    def bol_to_next_bol(self):
        # Format and discard one visual line; this advances the point.
        self.format_line()
```

- [ ] **Step 5: Rewrite `bol_to_prev_bol` as a backscan + forward walk**

```python
    def bol_to_prev_bol(self):
        if self.doc.at_start():
            return
        pt = self.doc.get_point()
        # Step back one char to escape current BoL, then backscan.
        self.doc.move_point(-1)
        self.doc.find_char_backward('\n')
        if not self.doc.at_start() and self.doc.get_char() == '\n':
            self.doc.move_point(1)
        # Forward-walk visual lines until next BoL would pass pt.
        while True:
            prev_bol = self.doc.get_point()
            self.format_line()
            if self.doc.get_point().is_at_or_after(pt):
                self.doc.set_point(prev_bol)
                return
```

- [ ] **Step 6: Delete `ladder_point` entirely**

Remove the `ladder_point` method (the entire block after `### Internal beginning-of-line routines`).

- [ ] **Step 7: Strip ladder bookkeeping from `format_line`**

In `format_line`, remove the lines that touch `self.bol_ladder`:

```python
        pt = self.doc.get_point()
        if pt not in self.bol_ladder:                           # DELETE
            self.bol_ladder = Ladder([pt])                      # DELETE
            logging.info(f'format_line reset to [{pt.position()}]')  # DELETE
        extend_ladder = pt == self.bol_ladder[-1]               # DELETE
```

And later:

```python
        pt = self.doc.get_point()
        if extend_ladder and pt != self.bol_ladder[-1]:        # DELETE
            self.bol_ladder.append(pt)                          # DELETE
```

- [ ] **Step 8: Remove `bol_ladder`-touching tests in `tests/test_layout.py`**

Run:

```bash
grep -n bol_ladder tests/test_layout.py
```

Delete or rewrite any test that asserts directly on `bol_ladder`. The four tests in `test_layout.py` (as of now) only exercise `bol_to_next_bol`, `format_line`, and `offset_for_column` — they should not touch `bol_ladder` directly. If the file is unchanged, no edit needed.

- [ ] **Step 9: Run all tests and goldens**

```bash
uv run pytest -v
```

Expected: ALL PASS, including `test_render_golden.py` (the goldens captured against pre-rewrite code must still match).

If goldens fail: **stop and investigate.** A golden mismatch here means the naive renderer produces different bytes than the cached one — that is a behavior change, not a perf change. Likely candidates: subtle off-by-one in the new `bol_to_prev_bol`, or `find_top` interactions in `display.py` (handled in next task). Use `git diff`, the golden's location of mismatch, and `pytest --tb=long` to find the divergence.

- [ ] **Step 10: Commit**

```bash
git add src/ptedit/layout.py tests/test_layout.py
git commit -m "refactor(stage1): strip BoL ladder, navigate via backscan + forward walk"
```

---

### Task 1.4: Strip `preferred_top` caching from `Display`

**Files:**
- Modify: `src/ptedit/display.py`

`Display.find_top` currently uses `preferred_top` as a sticky anchor. With no ladder, holding a sticky anchor across edits is fragile (a `Location` may go stale on edit). For the naive baseline, recompute top from cursor on every paint.

- [ ] **Step 1: Drop `preferred_top` initialization**

In `Display.__init__`, remove:

```python
        self.preferred_top: Location | None = None
```

And remove the `recenter` method (no longer meaningful — every paint already fully recentes):

```python
    def recenter(self):                                          # DELETE
        """Force point back to preferred row by invalidating sticky top"""  # DELETE
        self.preferred_top = None                                # DELETE
```

If `recenter` is wired to a key binding, find the binding (`grep -rn recenter src/`) and replace the action with a no-op or stub that just calls `paint()`.

- [ ] **Step 2: Rewrite `find_top` to backscan unconditionally**

Replace the body of `find_top`:

```python
    def find_top(self):
        """Move the point to the top-left of the screen by walking
        `preferred_row` visual lines back from the current point."""
        # Step back one BoL at a time until we have preferred_row lines above,
        # or until we hit doc start.
        self.layout.clamp_to_bol()
        for _ in range(self.preferred_row):
            if self.doc.at_start():
                return
            self.layout.bol_to_prev_bol()
```

- [ ] **Step 3: Remove the `change_handler` chain to `layout` if it now no-ops**

In `Display.change_handler`:

```python
    def change_handler(self, start: Location, end: Location):
        self.layout.change_handler(start, end)   # currently a no-op; keep the call
```

Keep the call intact — Stage 2 will re-add work behind it.

- [ ] **Step 4: Run all tests**

```bash
uv run pytest -v
```

Expected: ALL PASS.

If `test_display.py::test_frame` fails because it pokes `dpy.preferred_top = None`, update the test:

```python
def test_frame():
    alice = document.Document(ALICE_NL)
    alice.set_point_start().move_point(595)
    pt = alice.get_point()
    dpy = display.Display(alice, display.Screen(24, 72))
    # preferred_top no longer exists; find_top recomputes every call
    dpy.find_top()
    top = alice.get_point()
    s = alice.get_data(top, pt)
    assert s.startswith('the book her sister was reading')
```

- [ ] **Step 5: Commit**

```bash
git add src/ptedit/display.py tests/test_display.py
git commit -m "refactor(stage1): drop preferred_top sticky anchor; recompute top each paint"
```

---

### Task 1.5: Capture naive baseline perf

**Files:**
- Modify: `docs/plans/perf-baseline.md`

- [ ] **Step 1: Run all four perftest scenarios**

```bash
for s in insert up_from_end pgup_from_end pgdn_from_top; do
    echo -n "$s: "; uv run python -m ptedit -P $s tests/alice1flow.asc
done
```

- [ ] **Step 2: Append "Stage 1: naive baseline" section to `docs/plans/perf-baseline.md`**

```markdown
## Stage 1 — naive baseline (rendering redesign)

No ladder; every frame backscans from the cursor and reformats. Captured
at commit `<git rev-parse HEAD>`.

| scenario       | pre-rewrite fps | naive fps | ratio |
|----------------|-----------------|-----------|-------|
| insert         | <N1>            | <N>       | <%>   |
| up_from_end    | <N1>            | <N>       | <%>   |
| pgup_from_end  | <N1>            | <N>       | <%>   |
| pgdn_from_top  | <N1>            | <N>       | <%>   |

Severe regression expected — this is the floor against which Stage 2
is measured.
```

Replace `<N1>` with the values from Task 1.1, `<N>` with the new measurements, `<%>` with `naive / pre-rewrite × 100` rounded.

- [ ] **Step 3: Commit**

```bash
git add docs/plans/perf-baseline.md
git commit -m "perf(stage1): record naive baseline; floor for ladder benchmarking"
```

---

## Stage 2 — New Ladder

### Task 2.1: Implement the `Ladder` class in isolation

**Files:**
- Modify: `src/ptedit/layout.py`
- Modify: `tests/test_layout.py`

The new `Ladder` replaces the deque. List-based for Python clarity (the Forth port will use a true ring buffer per `docs/rendering.md`). The `[first, top, last)` semantics from the spec are preserved as `first == 0`, `last == len(slots)`, and `top` as a plain integer index.

- [ ] **Step 1: Write failing tests for the Ladder**

Add to the **top** of `tests/test_layout.py`, before `test_bol`:

```python
from ptedit.layout import Ladder
from ptedit.location import Location


def _locs(n: int) -> list[Location]:
    """Distinct, ordered Locations for ladder-mechanics tests."""
    from ptedit.document import Document
    d = Document('x' * (n * 2))
    out = []
    for i in range(n):
        d.set_point_start().move_point(i * 2)
        out.append(d.get_point())
    return out


def test_ladder_empty():
    lad = Ladder()
    assert not lad
    assert len(lad) == 0
    assert lad.top == 0
    assert lad.first == 0
    assert lad.last == 0


def test_ladder_append_and_iter():
    lad = Ladder()
    locs = _locs(5)
    for loc in locs:
        lad.append(loc)
    assert bool(lad)
    assert len(lad) == 5
    assert list(lad) == locs
    assert lad[0] == locs[0]
    assert lad[-1] == locs[-1]


def test_ladder_truncate():
    lad = Ladder()
    locs = _locs(5)
    for loc in locs:
        lad.append(loc)
    lad.truncate_to(2)
    assert list(lad) == locs[:2]


def test_ladder_reset():
    lad = Ladder()
    for loc in _locs(3):
        lad.append(loc)
    new_anchor = _locs(1)[0]
    lad.reset(new_anchor)
    assert list(lad) == [new_anchor]
    assert lad.top == 0


def test_ladder_drops_oldest_past_max():
    """Past MAX entries, oldest is discarded; top index follows."""
    lad = Ladder()
    locs = _locs(Ladder.MAX + 3)
    for loc in locs:
        lad.append(loc)
    assert len(lad) == Ladder.MAX
    assert list(lad) == locs[3:]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/test_layout.py::test_ladder_empty -v
```

Expected: FAIL with `ImportError` or `AttributeError` — `Ladder` does not exist yet.

- [ ] **Step 3: Implement the `Ladder` class**

Add to `src/ptedit/layout.py`:

```python
class Ladder:
    """
    Sequence of BoL Locations covering the visible region and its
    immediate neighborhood, per docs/rendering.md.

    The doc describes a 64-slot ring buffer with three indices
    (first/top/last) — that's the contract for the 6502/Forth port,
    where the byte budget matters. This Python reference uses a plain
    list for clarity:

        first == 0           (always; we trim from the front)
        last  == len(slots)  (always)
        top                  is a simple integer index in [first, last)

    The algorithm in the doc is unchanged; only the data structure
    differs. A Forth port should re-derive the wrap-aware index math
    from the spec.
    """
    MAX = 64

    def __init__(self):
        self.slots: list[Location] = []
        self.top: int = 0

    @property
    def first(self) -> int:
        return 0

    @property
    def last(self) -> int:
        return len(self.slots)

    def __bool__(self) -> bool:
        return bool(self.slots)

    def __len__(self) -> int:
        return len(self.slots)

    def __iter__(self):
        return iter(self.slots)

    def __getitem__(self, i: int) -> Location:
        return self.slots[i]

    def append(self, loc: Location):
        self.slots.append(loc)
        if len(self.slots) > self.MAX:
            self.slots.pop(0)
            self.top = max(0, self.top - 1)

    def truncate_to(self, count: int):
        """Keep the first `count` entries; discard the rest."""
        assert 0 <= count <= len(self.slots)
        del self.slots[count:]
        if self.top >= count:
            self.top = max(0, count - 1)

    def reset(self, anchor: Location):
        """Discard everything; seed with a single anchor at top."""
        self.slots = [anchor]
        self.top = 0
```

- [ ] **Step 4: Run ladder tests to verify they pass**

```bash
uv run pytest tests/test_layout.py -v -k ladder
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ptedit/layout.py tests/test_layout.py
git commit -m "feat(stage2): introduce Ladder with first/top/last semantics"
```

---

### Task 2.2: Wire ladder into `Layout` with edit-time truncation

**Files:**
- Modify: `src/ptedit/layout.py`

- [ ] **Step 1: Add `Edit.unlinked_pieces` plumbing if not already present**

Inspect `src/ptedit/edit.py`:

```bash
grep -n "unlinked\|linked\|pieces" src/ptedit/edit.py | head -20
```

If `Edit` does not already track which pieces were unlinked by an edit, add a `unlinked: set[Piece]` field to it and populate it in the edit application path. The validity check in `change_handler` requires this.

If `Edit` already tracks this under a different name, note it and skip this step.

- [ ] **Step 2: Add `bol_ladder` field and the `Ladder` import path is local**

In `Layout.__init__` (currently no `bol_ladder` after Stage 1), add:

```python
        self.bol_ladder = Ladder()
```

- [ ] **Step 3: Implement edit-time truncation in `change_handler`**

The signature `change_handler(start: Location, end: Location)` is currently invoked from `Document.watch`. To get the unlinked-pieces set, either thread it through (preferred — modify the signal) or look it up via the `Document`/`Edit` log. Pick whichever is simpler given current code; the goal is `change_handler` having access to the edit's unlinked-pieces set.

Implement:

```python
    def change_handler(self, start: Location, end: Location, unlinked: set | None = None):
        """Truncate the ladder at the first invalid entry per docs/rendering.md."""
        if not self.bol_ladder:
            return
        edit_pos = start.position()
        keep = 0
        for entry in self.bol_ladder:
            piece, _offset = entry.tuple()
            # Validity rule 1: piece not in unlinked set.
            if unlinked is not None and piece in unlinked:
                break
            # Validity rule 2: entry more than `cols` chars before edit.
            if entry.position() + self.cols > edit_pos:
                break
            keep += 1
        self.bol_ladder.truncate_to(keep)
        # If top now points past the surviving range, the ladder is unusable;
        # Phase 1 in the next paint will re-anchor.
        if self.bol_ladder and self.bol_ladder.top >= len(self.bol_ladder):
            self.bol_ladder = Ladder()
```

- [ ] **Step 4: Test edit-time truncation**

Add to `tests/test_layout.py`:

```python
def test_change_handler_truncates_at_edit():
    from ptedit import document
    doc = document.Document('line 1\nline 2\nline 3\nline 4\n')
    lay = layout.Layout(doc, 24, 24, 8)
    # Build a ladder by walking forward
    for _ in range(3):
        lay.bol_to_next_bol()  # rebuilds ladder via Phase 1 (Task 2.3)
    n = len(lay.bol_ladder)
    # Simulate an edit at position 14 (middle of "line 2")
    edit_start = doc.get_point().move(14 - doc.get_point().position()) if False else None
    # Direct call for unit test purposes — production wires this via Document.watch
    doc.set_point_start().move_point(14)
    lay.change_handler(doc.get_point(), doc.get_point(), unlinked=set())
    # Entries before pos (14 - cols=24) → 0 should be kept; rest truncated.
    assert all(e.position() + lay.cols <= 14 for e in lay.bol_ladder)
```

This test depends on Task 2.3 (which implements the rebuild). If the test fails because `bol_to_next_bol` does not yet build the ladder, mark this test xfail until Task 2.3, then re-enable.

- [ ] **Step 5: Run goldens to verify behavior unchanged**

```bash
uv run pytest tests/test_render_golden.py -v
```

Expected: PASS (the ladder is being built and truncated, but `paint()` still does full redraw, so observable behavior matches goldens).

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/layout.py src/ptedit/edit.py tests/test_layout.py
git commit -m "feat(stage2): wire ladder edit-time truncation per validity rules"
```

---

### Task 2.3: Implement Phase 1 — cursor location and re-anchor

**Files:**
- Modify: `src/ptedit/layout.py`

This task implements the three-case cursor-location logic. Re-anchor first (it's the fallback used by the others), then bracketed/extension paths. After this task, `bol_to_next_bol`, `bol_to_prev_bol`, and `clamp_to_bol` route through the ladder.

- [ ] **Step 1: Implement `_reanchor`**

```python
    def _reanchor(self, cursor: Location):
        """
        Rebuild the ladder fresh: backscan from cursor to nearest newline
        (or doc start), seed the ladder with that anchor, and forward-format
        until cursor is bracketed.
        """
        save_pt = self.doc.get_point()
        self.doc.set_point(cursor)
        if not self.doc.at_start():
            self.doc.move_point(-1)
            self.doc.find_char_backward('\n')
            if not self.doc.at_start() and self.doc.get_char() == '\n':
                self.doc.move_point(1)
        anchor = self.doc.get_point()
        self.bol_ladder.reset(anchor)
        # Forward-format until the cursor lies within the cached range.
        while self.doc.get_point().is_strictly_before(cursor):
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
        # Top is the screen-anchor; for re-anchor, we set it = first.
        self.bol_ladder.top = self.bol_ladder.first
        self.doc.set_point(save_pt)
```

- [ ] **Step 2: Implement `_locate_cursor` returning a case tag**

```python
    def _locate_cursor(self, cursor: Location) -> str:
        """Phase 1 step 2 from docs/rendering.md.

        Returns one of: 'bracketed', 'extend', 'reanchor'.
        """
        lad = self.bol_ladder
        if not lad:
            return 'reanchor'
        if cursor.is_strictly_before(lad[0]):
            return 'reanchor'
        # If cursor sits before the last entry, it must be bracketed by
        # some consecutive pair (slots are sorted by document position).
        if cursor.is_strictly_before(lad[-1]):
            return 'bracketed'
        # Cursor is at or past the last entry — extend if close enough.
        gap = cursor.distance_after(lad[-1])
        if gap is None or gap > self.rows * self.cols:
            return 'reanchor'
        return 'extend'
```

- [ ] **Step 3: Implement `_extend_to`**

```python
    def _extend_to(self, cursor: Location):
        """Format forward from the last cached BoL until cursor is bracketed."""
        save_pt = self.doc.get_point()
        self.doc.set_point(self.bol_ladder[-1])
        added = 0
        while self.doc.get_point().is_strictly_before(cursor) and added <= self.rows:
            self.format_line()
            self.bol_ladder.append(self.doc.get_point())
            added += 1
        self.doc.set_point(save_pt)
```

- [ ] **Step 4: Public entry point used by nav primitives**

```python
    def _ensure_bracketed(self, cursor: Location | None = None):
        """
        Phase 1: ensure the ladder brackets `cursor` (defaults to current point).
        """
        if cursor is None:
            cursor = self.doc.get_point()
        match self._locate_cursor(cursor):
            case 'bracketed':
                return
            case 'extend':
                self._extend_to(cursor)
            case 'reanchor':
                self._reanchor(cursor)
```

- [ ] **Step 5: Rewrite the BoL nav primitives to use the ladder**

These benefit from a small helper that returns the index of the line
containing a given position (linear scan; the ladder is small):

```python
    def _find_line_index(self, cursor: Location) -> int:
        """Index of the ladder entry whose line contains `cursor`."""
        lad = self.bol_ladder
        for i in range(len(lad) - 1):
            if cursor.is_strictly_before(lad[i + 1]):
                return i
        return len(lad) - 1

    def clamp_to_bol(self):
        if self.doc.at_start():
            return
        cursor = self.doc.get_point()
        self._ensure_bracketed(cursor)
        i = self._find_line_index(cursor)
        self.doc.set_point(self.bol_ladder[i])

    def bol_to_next_bol(self):
        bol = self.doc.get_point()
        self._ensure_bracketed(bol)
        i = self._find_line_index(bol)
        if i + 1 < len(self.bol_ladder):
            self.doc.set_point(self.bol_ladder[i + 1])
            return
        # bol is the newest entry; format one more line to advance.
        self.format_line()
        if not self.doc.at_end():
            self.bol_ladder.append(self.doc.get_point())

    def bol_to_prev_bol(self):
        if self.doc.at_start():
            return
        bol = self.doc.get_point()
        self._ensure_bracketed(bol)
        i = self._find_line_index(bol)
        if i > 0:
            self.doc.set_point(self.bol_ladder[i - 1])
            return
        # bol is the oldest entry — re-anchor before it.
        self.doc.move_point(-1)
        self._reanchor(self.doc.get_point())
        # Now bol must be the newest of a fresh ladder; new prev is at -2.
        if len(self.bol_ladder) >= 2:
            self.doc.set_point(self.bol_ladder[-2])
```

- [ ] **Step 6: Run all tests including goldens**

```bash
uv run pytest -v
```

Expected: ALL PASS. Goldens are the load-bearing check — observable paint output must match Stage 1.

If goldens fail: the ladder rebuild path is producing slightly different BoLs than the naive backscan. Compare the first N bytes of failing goldens (use `xxd tests/golden/<name>.bin | head` and compare with the pre-rewrite version saved in git).

- [ ] **Step 7: Commit**

```bash
git add src/ptedit/layout.py
git commit -m "feat(stage2): Phase 1 — bracketed / extend / reanchor cursor location"
```

---

### Task 2.4: Restore `preferred_top` as a ladder index

**Files:**
- Modify: `src/ptedit/display.py`

The ladder's `top` index serves the same role as the old `preferred_top` Location, but indexed and survives edits via the truncation logic.

- [ ] **Step 1: Update `find_top` to use `ladder.top`**

```python
    def find_top(self):
        """Position the screen so the cursor sits roughly at preferred_row.

        Updates `layout.bol_ladder.top` and moves point to that BoL.
        """
        self.layout._ensure_bracketed(self.doc.get_point())
        lad = self.layout.bol_ladder
        cursor_idx = self.layout._find_line_index(self.doc.get_point())
        # Aim for cursor sitting at preferred_row from the top.
        target_top = cursor_idx - self.preferred_row
        if target_top < 0:
            # Need entries we don't have above; ladder may already start
            # at doc-zero (re-anchor lands on nearest prior newline).
            target_top = 0
        lad.top = target_top
        self.doc.set_point(lad[target_top])
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest -v
```

Expected: ALL PASS, including goldens.

- [ ] **Step 3: Commit**

```bash
git add src/ptedit/display.py
git commit -m "feat(stage2): Display.find_top uses ladder.top as the screen anchor"
```

---

### Task 2.5: Phase 2 case dispatch in `paint`

**Files:**
- Modify: `src/ptedit/display.py`

The four cases from `docs/rendering.md` Phase 2 table. Initial implementation: only the **Full redraw** path is fully optimized; the other three fall through to full redraw too. We measure perf then optimize incrementally.

- [ ] **Step 1: Track `prev_top` across paints**

In `Display.__init__`, add:

```python
        self.prev_top_idx: int | None = None
        self.prev_last_idx: int | None = None
```

- [ ] **Step 2: Classify the case at the top of `paint`**

In `paint`, immediately after `self.find_top()` and before `self.scr.clear()`:

```python
        lad = self.layout.bol_ladder
        case = self._classify_paint_case(lad)
        # For now all four cases fall through to full redraw; perf tuning later.
```

- [ ] **Step 3: Implement `_classify_paint_case`**

```python
    def _classify_paint_case(self, lad) -> str:
        """Map the four cases from docs/rendering.md Phase 2 table."""
        if self.prev_top_idx is None:
            return 'full'
        top_unchanged = lad.top == self.prev_top_idx
        last_unchanged = lad.last == self.prev_last_idx
        all_rows_cached = lad.last >= lad.top + self.rows
        if top_unchanged and all_rows_cached and last_unchanged:
            return 'local_no_scroll'
        if top_unchanged and not all_rows_cached:
            return 'local_edit'
        if not top_unchanged and 0 <= lad.top < lad.last:
            return 'scroll'
        return 'full'
```

- [ ] **Step 4: Save indices at the end of `paint`**

Just before `return cursor`:

```python
        self.prev_top_idx = lad.top
        self.prev_last_idx = lad.last
```

- [ ] **Step 5: Run tests including goldens**

```bash
uv run pytest -v
```

Expected: ALL PASS. Behavior must be unchanged — we are only classifying, not yet optimizing.

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/display.py
git commit -m "feat(stage2): classify Phase 2 paint cases (no behavior change yet)"
```

---

### Task 2.6: Capture new ladder perf

**Files:**
- Modify: `docs/plans/perf-baseline.md`

- [ ] **Step 1: Run all four perftest scenarios**

```bash
for s in insert up_from_end pgup_from_end pgdn_from_top; do
    echo -n "$s: "; uv run python -m ptedit -P $s tests/alice1flow.asc
done
```

- [ ] **Step 2: Append a "Stage 2: new ladder" section to `docs/plans/perf-baseline.md`**

```markdown
## Stage 2 — new ladder (rendering redesign)

List-based ladder with `[first, top, last)` semantics per `docs/rendering.md`.
Phase 1 cursor-location logic in place; Phase 2 case classification
in place but only full-redraw path is exercised. Captured at commit
`<git rev-parse HEAD>`.

| scenario       | pre-rewrite fps | naive fps | new fps | new vs pre | new vs naive |
|----------------|-----------------|-----------|---------|------------|--------------|
| insert         | <N0>            | <N1>      | <N>     | <%>        | <%>          |
| up_from_end    | <N0>            | <N1>      | <N>     | <%>        | <%>          |
| pgup_from_end  | <N0>            | <N1>      | <N>     | <%>        | <%>          |
| pgdn_from_top  | <N0>            | <N1>      | <N>     | <%>        | <%>          |
```

- [ ] **Step 3: Commit**

```bash
git add docs/plans/perf-baseline.md
git commit -m "perf(stage2): record new ladder perf vs naive and pre-rewrite baselines"
```

---

### Task 2.7: Phase 2 fast-path for "Local move, no scroll" (CONDITIONAL)

**Skip this task** if the perf in Task 2.6 already meets or exceeds pre-rewrite numbers across all four scenarios. The illustrative goal is satisfied by the case-classification logic in Task 2.5; an attribute-flip fast path adds complexity that doesn't translate cleanly to the Forth port unless required by perf.

**Files:**
- Modify: `src/ptedit/display.py`

The cheapest optimization: when no edit and no scroll, the data on screen is valid; only cursor/highlight cells flip.

- [ ] **Step 1: Refactor `paint` to split data-format and attribute-flip**

Extract the per-cell `self.scr.put(ch, highlight)` loop into `_emit_line(line, col_map, ...)` so it can be called either freshly per row, or skipped when the data on screen is valid.

- [ ] **Step 2: Track previous cursor and previous mark to compute attribute deltas**

In `Display.__init__`:

```python
        self.prev_cursor: tuple[int, int] | None = None
        self.prev_mark_cell: tuple[int, int] | None = None
```

- [ ] **Step 3: In `paint`, when case == `'local_no_scroll'`, skip the per-row format loop**

```python
        if case == 'local_no_scroll' and self.prev_cursor is not None:
            self._flip_attrs(prev_cursor=self.prev_cursor, new_cursor=..., ...)
            self.prev_cursor = ...
            return ...
```

(Detailed implementation depends on how cursor/highlight cells map; consult the existing `paint` body.)

- [ ] **Step 4: Run tests including goldens**

```bash
uv run pytest -v
```

Expected: ALL PASS. Goldens use a recording `Screen` that captures every `put`, so a path that legitimately skips puts will *change* the recorded byte stream. **Update the goldens** if the no-scroll cases now produce shorter event streams — but only after manually verifying that the visible content (chars at each cell) matches the prior fixture's content.

- [ ] **Step 5: Re-measure perf and append a delta table**

```bash
for s in insert up_from_end pgup_from_end pgdn_from_top; do
    echo -n "$s: "; uv run python -m ptedit -P $s tests/alice1flow.asc
done
```

Append to `docs/plans/perf-baseline.md` under a "Stage 2 + local-no-scroll fast path" subsection.

- [ ] **Step 6: Commit**

```bash
git add src/ptedit/display.py docs/plans/perf-baseline.md tests/golden/
git commit -m "perf(stage2): Phase 2 fast path for local-move-no-scroll (attr-flip only)"
```

---

### Task 2.8: Final type-check and merge prep

**Files:**
- (verification only)

- [ ] **Step 1: Type-check**

```bash
uv run pyright src/ tests/
```

Expected: 0 errors. Address any new errors introduced.

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/ tests/
```

Expected: clean. Fix any issues.

- [ ] **Step 3: Run the full test suite one more time**

```bash
uv run pytest -v
```

Expected: ALL PASS.

- [ ] **Step 4: Review `git log` since branch creation**

```bash
git log --oneline main..HEAD
```

Confirm the commit sequence reads cleanly: design doc → pre-rewrite perf → goldens → strip → naive perf → ring buffer → wire ladder → Phase 1 → find_top → Phase 2 classify → ladder perf → Phase 2 optimize.

- [ ] **Step 5: Open PR or hand back**

Stop here for human review. Recommend reviewer compare:
- `docs/rendering.md` against final `src/ptedit/layout.py` to verify the implemented design matches the spec.
- `docs/plans/perf-baseline.md` to verify perf is at or above pre-rewrite numbers.

---

## Self-Review Notes

**Spec coverage:** Every section of `docs/rendering.md` maps to a task:
- Constraints — Python relaxes the byte budget; the spec's 64-slot ring is enforced as `Ladder.MAX = 64` with append-discards-oldest semantics. Forth port re-derives the wrap-aware index math.
- Ladder State (first/top/last, half-open) → Task 2.1 (Pythonic list with `first == 0`, `last == len(slots)`, integer `top`).
- Phase 1 (edit-truncate / locate cursor / extend / reanchor) → Tasks 2.2 and 2.3.
- Phase 2 cases → Task 2.5 (classify) + Task 2.7 (conditional fast path).
- Validity (unlinked-pieces + cols margin) → Task 2.2.
- Wrap-propagation example — pure exposition, no code.
- Alternatives considered (per-piece NL counts, per-entry rescue, P→pre remap) — explicitly excluded; no tasks.

**KISS / DRY / SOLID review:**
- KISS: list-based ladder, single `_find_line_index` helper used by `clamp_to_bol`, `bol_to_next_bol`, `bol_to_prev_bol`. No ring-aware index helpers needed.
- DRY: `_ensure_bracketed` is the single Phase 1 entry point used by all nav primitives.
- SOLID: `Ladder` has one responsibility (sequence of BoLs with truncate/append/reset). `Layout` orchestrates Phase 1. `Display` orchestrates Phase 2 + screen output. No cross-leakage of the line-format details.

**Known soft spots:**
- `Edit.unlinked_pieces` plumbing (Task 2.2 Step 1) is exploratory — adjust to whatever the existing `Edit` API actually exposes.
- `Document.find_char_backward` / `get_char` / `Location.is_strictly_before` etc. are assumed by the naive backscan code — verify exact spellings in `src/ptedit/document.py` and `src/ptedit/location.py` before Stage 1 Task 1.3 Step 3.
- Phase 2 fast paths beyond `local_no_scroll` (i.e. `scroll` block-copy, `local_edit` partial reformat) are intentionally deferred — the Python implementation is illustrative; if the Forth port needs them, they can be added at that time.

**Forth-port guidance:** the `Ladder` docstring explicitly points back to `docs/rendering.md` for the ring-buffer semantics. The Forth port should treat the Python `slots` list as a logical sequence and re-derive `(first + i) mod size` indexing from the spec.

**Goldens contract:** Through Stages 1 and 2 Tasks 2.1–2.6, the four golden fixtures captured in Task 1.2 must be byte-identical. Task 2.7 is the first task allowed to legitimately change golden byte streams (because skipped `put` calls produce a shorter event stream); the change must be reviewed by inspecting the *visible* state (cell-by-cell content) before the fixture is regenerated.
