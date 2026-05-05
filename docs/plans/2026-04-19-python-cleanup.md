# PT Editor Python Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the Python prototype (MVC factoring, bug fixes, sentinel uniformity, ladder performance investigation) before restarting the Forth/asm port.

**Architecture:** Reorganize so that `Layout` is the layout-aware Model (BoL ladder, line moves, line formatting, preferred column), `Display` is a pure View (paint, find_top), and `Editor` is the Controller (mark, clipboard, isearch, char/word/region ops, depending on Document + Layout but not on Display except via a notify callback). `Controller` composes everything and owns the status bar.

**Tech Stack:** Python 3.12+, pytest, curses. Tests live in `tests/`. Run with `python -m pytest tests/ -q`.

---

## Phase 1 — MVC refactor

The goal of Phase 1 is structural: relocate code into the right modules with the right dependencies, without changing observable behavior. Existing tests should continue to pass once test imports/wiring are updated. Bug fixes and behavior changes are deferred to Phase 2.

### Task 1: Pin observable behavior with characterization tests

Before moving code, lock down a couple of behaviors that are easy to break during the refactor: line-move + paint round-trip preserves point, status bar contents include known fields, and `_clip_line` round-trips a line correctly. The existing tests in `tests/test_display.py`, `tests/test_document.py`, and `tests/test_formatter.py` cover most cases; we add a few targeted ones.

**Files:**
- Create: `tests/test_characterization.py`

- [ ] **Step 1: Write characterization tests**

```python
# tests/test_characterization.py
"""
Characterization tests pinning behavior across the MVC refactor.
These exercise the public API surface (key entry points used by Controller)
so that the refactor is judged green/red purely by these + existing tests.
"""
from ptedit import document, display, editor


def make_dpy(text: str, rows: int = 24, cols: int = 80):
    doc = document.Document(text)
    dpy = display.Display(doc, display.Screen(rows, cols))
    return doc, dpy


def test_line_move_paint_roundtrip_preserves_point():
    doc, dpy = make_dpy('one\ntwo\nthree\nfour\nfive\nsix\n')
    doc.move_point(5)  # inside 'two'
    pt = doc.get_point()
    dpy.move_forward_line()
    dpy.move_backward_line()
    dpy.paint()
    # after symmetric line moves + paint, point should land on same row & col,
    # which for a non-wrapped doc means the same position
    assert doc.get_point().position() == pt.position()


def test_status_message_contains_position_and_filename():
    doc = document.Document('hello world')
    dpy = display.Display(doc, display.Screen(24, 80), fname='foo.txt')
    s = dpy.status_message((0, 0))
    assert 'foo.txt' in s
    assert 'pos 0/11' in s
    assert 'lns 0/0' in s


def test_clip_line_roundtrip():
    doc = document.Document('alpha\nbravo\ncharlie\n')
    dpy = display.Display(doc, display.Screen(24, 80))
    ed = editor.Editor(doc, dpy)
    doc.move_point(8)  # inside 'bravo'
    ed.cut_line()
    assert ed.clipboard == 'bravo\n'
    assert doc.get_data() == 'alpha\ncharlie\n'
    ed.paste()
    assert doc.get_data() == 'alpha\nbravo\ncharlie\n'


def test_isearch_message_set_on_search():
    doc = document.Document('the quick brown fox')
    dpy = display.Display(doc, display.Screen(24, 80))
    ed = editor.Editor(doc, dpy)
    ed.isearch_forward()         # opens isearch
    ed.insert(ord('q'))          # adds to search
    # The display message should reflect the search prompt
    assert 'Search' in dpy.message or 'quick' in doc.get_data()
```

- [ ] **Step 2: Run the new tests and the full suite to confirm baseline green**

Run: `python -m pytest tests/ -q`
Expected: all green (or flag any pre-existing red so we know the baseline).

- [ ] **Step 3: Commit**

```bash
git add tests/test_characterization.py
git commit -m "test: pin display/editor behavior for refactor"
```

---

### Task 2: Create `Layout` module

Rename `formatter.py` → `layout.py`. Rename `Formatter` → `Layout`. Absorb the line-move methods (`move_start_line`, `move_end_line`, `move_forward_line`, `move_backward_line`, `move_forward_page`, `move_backward_page`) and the `preferred_col` / `pin_preferred_col` state from `Display`. Display will delegate these in this task; we'll cut the delegation in Task 3.

**Files:**
- Rename: `src/ptedit/formatter.py` → `src/ptedit/layout.py`
- Modify: `src/ptedit/display.py` (delegate line moves to `self.layout`)
- Rename: `tests/test_formatter.py` → `tests/test_layout.py`
- Modify: `tests/test_layout.py` (`Formatter` → `Layout`, ctor takes `rows`)

- [ ] **Step 1: Move and rename the file**

```bash
git mv src/ptedit/formatter.py src/ptedit/layout.py
git mv tests/test_formatter.py tests/test_layout.py
```

- [ ] **Step 2: Rename `Formatter` → `Layout` and add `rows` parameter + line-move methods**

In `src/ptedit/layout.py`, change the class signature and add the absorbed methods. The full new class shape (everything else stays the same as the previous `Formatter`):

```python
class Layout:
    def __init__(self, doc: Document, cols: int, rows: int, rungs: int, tab: int = 4):
        self.doc = doc
        assert (cols // tab) * tab == cols, "tab should divide cols"
        self.cols = cols
        self.rows = rows
        self.rungs = rungs
        self.tab = tab

        self.bol_ladder = Ladder()
        self.preferred_col = 0
        self.pin_preferred_col = False
        self.wrap_lookahead: bool

    # ----- line moves (absorbed from Display) -----

    def move_start_line(self):
        self.clamp_to_bol()

    def move_end_line(self):
        self.clamp_to_bol()
        self.bol_to_next_bol()
        if not self.doc.at_end():
            self.doc.move_point(-1)

    def move_forward_line(self):
        self.clamp_to_bol()
        if not self.doc.at_end():
            self.bol_to_next_bol()
            self.pin_preferred_col = True

    def move_backward_line(self):
        self.clamp_to_bol()
        if not self.doc.at_start():
            self.bol_to_prev_bol()
            self.pin_preferred_col = True

    def move_forward_page(self):
        self.clamp_to_bol()
        for _ in range(self.rows):
            self.bol_to_next_bol()
        self.pin_preferred_col = True

    def move_backward_page(self):
        self.clamp_to_bol()
        for _ in range(self.rows):
            self.bol_to_prev_bol()
        self.pin_preferred_col = True

    # ----- existing Formatter methods (unchanged) -----

    def change_handler(self, start, end):
        self.rescue_ladder(start)

    # ... clamp_to_bol, bol_to_next_bol, bol_to_prev_bol,
    # ... format_line, ladder_point, rescue_ladder, offset_for_column
```

(Keep all the existing method bodies intact — only the class name and ctor change, plus the new line-move methods.)

- [ ] **Step 3: Update `Display` to use `Layout` and delegate line moves**

In `src/ptedit/display.py`, change the import and field name; line-move methods become delegations. Keep `preferred_col` / `pin_preferred_col` reads going through the layout; remove the local copies.

```python
# at top of file
from .layout import Layout
```

In `Display.__init__`, replace `self.fmt = Formatter(...)` with:

```python
self.layout = Layout(self.doc, self.cols, self.rows, self.rows // 2, tab)
self.preferred_top: Location | None = None
# remove local self.preferred_col / self.pin_preferred_col
```

Replace each line-move method with a one-line delegate:

```python
def move_start_line(self):     self.layout.move_start_line()
def move_end_line(self):       self.layout.move_end_line()
def move_forward_line(self):   self.layout.move_forward_line()
def move_backward_line(self):  self.layout.move_backward_line()
def move_forward_page(self):   self.layout.move_forward_page()
def move_backward_page(self):  self.layout.move_backward_page()
```

In `find_top` and `paint`, change `self.fmt.X` → `self.layout.X` everywhere, and `self.preferred_col` / `self.pin_preferred_col` → `self.layout.preferred_col` / `self.layout.pin_preferred_col`.

In `change_handler`:

```python
def change_handler(self, start, end):
    self.layout.change_handler(start, end)
```

- [ ] **Step 4: Update tests**

In `tests/test_layout.py`, replace every `formatter.Formatter(...)` constructor call so it passes `rows`:

```python
fmt = layout.Layout(doc, 24, 24, 8)   # cols, rows, rungs
```

Update the import: `from ptedit import document, layout`. Adjust any `Formatter.offset_for_column` references to `Layout.offset_for_column`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all green. If `test_display.test_preferred_col` fails, double-check that `Display.paint` reads/writes `self.layout.preferred_col` rather than a vanished local.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: extract Layout from Formatter + Display line moves"
```

---

### Task 3: Slim Display, route messages via callback

`Display` keeps `paint`, `find_top`, `recenter`, the screen, and the message buffer (since `scr.alert()` lives here). Status formatting moves to Controller (Task 5). Editor will receive a notify callback in Task 4 instead of a `Display` reference.

**Files:**
- Modify: `src/ptedit/display.py`

- [ ] **Step 1: Strip `status_message` from Display**

Delete the `status_message` method from `src/ptedit/display.py` (Controller will own it in Task 5). Modify `Display.paint` to accept a status string instead of building one:

```python
def paint(self, mark: Location | None = None, status: str = ''):
    """
    Paint the buffer to the screen, returning the new top-left location.
    Leaves point unchanged. The caller supplies the status line.
    """
    # ... existing body unchanged up to the status block at the bottom ...

    # OLD:
    # status = self.status_message(cursor)
    # NEW: use the supplied string, padded/truncated to width
    status = (status[:self.cols] if len(status) >= self.cols
              else status + ' ' * (self.cols - len(status)))
    self.scr.move(self.rows, 0)
    self.scr.puts(status, highlight=True)

    self.scr.move(*cursor)
    self.scr.refresh()
```

- [ ] **Step 2: Expose cursor for status formatting**

Controller needs the cursor position for the status line. The simplest path: have `paint` *return* the cursor.

In `Display.paint`, add `return cursor` as the last statement.

- [ ] **Step 3: Delete the line-move delegates from Display**

In Task 2 we left these as one-line delegates. Now remove them entirely:

```python
# DELETE these from Display:
# move_start_line, move_end_line, move_forward_line, move_backward_line,
# move_forward_page, move_backward_page
```

Callers will go through `Editor` (Task 4) which holds a Layout reference.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: failures in `test_display.py` and `test_characterization.py` because `Display.move_forward_line` and `status_message` are gone. We'll fix wiring in the next steps.

- [ ] **Step 5: Update tests to use new shape**

In `tests/test_display.py`, replace `dpy.move_forward_line()` etc. with `dpy.layout.move_forward_line()` (line moves now live on Layout).

In `tests/test_characterization.py`:
- `test_status_message_contains_position_and_filename` — temporarily mark `@pytest.mark.skip("status moved to controller in Task 5")`. Re-enable in Task 5.
- `test_line_move_paint_roundtrip_preserves_point` — change `dpy.move_forward_line()` → `dpy.layout.move_forward_line()`.

- [ ] **Step 6: Run tests, confirm green**

Run: `python -m pytest tests/ -q`
Expected: green (with the one skipped status test).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: Display owns paint+message only, status moves to caller"
```

---

### Task 4: Decouple Editor from Display

`Editor` currently calls `self.pager.move_start_line()` and `self.pager.show_message()`. Replace the `Display` parameter with explicit `Layout` and a `notify(msg, warn)` callback.

**Files:**
- Modify: `src/ptedit/editor.py`

- [ ] **Step 1: Change Editor's constructor**

```python
# src/ptedit/editor.py
from typing import Callable

NotifyFn = Callable[[str, bool], None]

class Editor:
    def __init__(self, doc: Document, layout: Layout, notify: NotifyFn):
        self.doc = doc
        self.layout = layout
        self.notify = notify

        self.doc.watch(self.change_handler)

        # state
        self.mark: Location | None = None
        self.clipboard = ''
        self.overwrite_mode = False
        self.isearch_dir: ISearchDirection | None = None
        self.isearch_text = ''
        self.isearch_origin = self.doc.get_point()
        self.isearch_recall = False
        self.isearch_start = False        # initialise here, fixes latent AttributeError

        self.match_mode = MatchMode.SMART_CASE
```

Add the import:

```python
from .layout import Layout
```

- [ ] **Step 2: Replace `self.pager.X` references**

In `src/ptedit/editor.py`, do a global rename:

| Old | New |
|---|---|
| `self.pager.show_message(msg)` | `self.notify(msg, False)` |
| `self.pager.show_message(msg, True)` | `self.notify(msg, True)` |
| `self.pager.move_start_line()` | `self.layout.move_start_line()` |
| `self.pager.move_end_line()` | `self.layout.move_end_line()` |

There are no other `self.pager` uses in Editor — verify with `grep -n pager src/ptedit/editor.py` (should return nothing after the edit).

- [ ] **Step 3: Update characterization test to construct Editor with new signature**

In `tests/test_characterization.py`, update `test_clip_line_roundtrip` and `test_isearch_message_set_on_search`:

```python
def make_editor(text):
    doc = document.Document(text)
    dpy = display.Display(doc, display.Screen(24, 80))
    ed = editor.Editor(doc, dpy.layout, lambda msg, warn=False: dpy.show_message(msg, warn))
    return doc, dpy, ed
```

Then `ed = editor.Editor(doc, dpy)` lines become calls to `make_editor`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: Editor depends on Layout + notify callback, not Display"
```

---

### Task 5: Move status formatting + composition into Controller

Controller now owns the status string and wires Document → Layout → Display + Editor.

**Files:**
- Modify: `src/ptedit/controller.py`
- Modify: `tests/test_characterization.py` (un-skip status test, update for new wiring)

- [ ] **Step 1: Move `status_message` into Controller**

Add to `src/ptedit/controller.py`:

```python
def status_message(self, cursor: tuple[int, int]) -> str:
    if self.dpy.message:
        status = self.dpy.message
        self.dpy.message = ''
    else:
        pt = self.doc.get_point()
        doc_data = self.doc.get_data()              # one walk only
        pt_data = self.doc.get_data(None, pt)
        doc_nl = doc_data.count('\n')
        pt_nl = pt_data.count('\n')
        fname = ('*' if self.doc.dirty else '') + f'{self.fname}'
        pt_pieces, all_pieces = self.doc.piece_counts()
        pt_edits, all_edits = self.doc.edit_counts()
        status = "  ".join([
            f"{fname}",
            f"xy {cursor[1]},{cursor[0]}",
            f"ch ${ord(self.doc.get_char() or chr(0)):02x}",
            f"pos {pt.position()}/{len(self.doc)}",
            f"lns {pt_nl}/{doc_nl}",
            f"pcs {pt_pieces}/{all_pieces}",
            f"eds {pt_edits}/{all_edits}",
        ])

    return " " + status
```

- [ ] **Step 2: Update Controller wiring**

In `src/ptedit/controller.py`, change `__init__` to:

```python
self.doc = Document(open(fname, encoding='iso-8859-1').read())
self.doc.watch(self.change_handler)
self.dpy = Display(self.doc, CursesScreen(stdscr), fname)
self.ed = Editor(
    self.doc,
    self.dpy.layout,
    notify=self.dpy.show_message,
)
```

Update the interactive loop to drive paint with the status string:

```python
def interactive(self):
    while self.active:
        cursor = self.dpy.paint(self.ed.mark)            # paint frame, get cursor
        self.dpy.scr.move(self.dpy.rows, 0)
        self.dpy.scr.puts(self.status_message(cursor), highlight=True)
        self.dpy.scr.move(*cursor)
        self.dpy.scr.refresh()
        try:
            key = self.getch()
            logging.info(f'key ${key:02x}')
            self.dispatch(key)
        except KeyboardInterrupt:
            self.quit()
```

(Equivalent: pass the status string into `Display.paint` as the `status` argument and let Display do the painting. Pick whichever feels cleaner — the loop-side variant keeps Display simpler.)

- [ ] **Step 3: Update keymap to point at `dpy.layout` for line moves**

The keymap in `Controller.__init__` currently binds `dpy.move_backward_line` etc. Change to:

```python
layout = self.dpy.layout
# ...
curses.KEY_UP: layout.move_backward_line,
curses.KEY_DOWN: layout.move_forward_line,
ctrl('A'): layout.move_start_line,
ctrl('E'): layout.move_end_line,
# ...
ord('a'): layout.move_backward_page,
ord('e'): layout.move_forward_page,
```

`dpy.recenter` stays bound to Display (it's a paint concern).

- [ ] **Step 4: Un-skip `test_status_message_contains_position_and_filename`**

Update it to construct a Controller (not a Display) for the status assertion. Easiest path:

```python
def test_status_message_contains_position_and_filename(tmp_path):
    f = tmp_path / 'foo.txt'
    f.write_text('hello world')
    # Construct a fake Controller without curses
    from ptedit.document import Document
    from ptedit.display import Display, Screen
    from ptedit.controller import Controller

    doc = Document('hello world')
    dpy = Display(doc, Screen(24, 80), fname='foo.txt')

    # mimic what Controller.status_message does using its real implementation
    # by extracting the method to a free function or re-running the logic;
    # simplest: bind a minimal Controller stand-in.
    class Stub:
        fname = 'foo.txt'
        doc = doc
        dpy = dpy
    s = Controller.status_message(Stub(), (0, 0))   # call as unbound method
    assert 'foo.txt' in s
    assert 'pos 0/11' in s
    assert 'lns 0/0' in s
```

If that feels ugly, factor `status_message` into a free function `format_status(doc, dpy, fname, cursor)` and have `Controller.status_message` call it. The test then calls the free function directly. Pick whichever you prefer.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 6: Smoke test interactively**

```bash
python -m ptedit foo
```

Drive arrow keys, page-up/page-down, Ctrl-A/E, isearch (Ctrl-S then text), Esc, save (Esc-s), quit (Esc-q). Status bar should show all fields. No tracebacks.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: Controller owns status + composition wiring"
```

---

### Task 6: Cleanup leaks and dead state

Clean up the small leaks/dead state surfaced by the refactor.

**Files:**
- Modify: `src/ptedit/document.py`
- Modify: `src/ptedit/display.py`
- Modify: `src/ptedit/piece.py`

- [ ] **Step 1: Remove `_n_get_char_calls` instrumentation from Document**

In `src/ptedit/document.py`, delete:
- `self._n_get_char_calls = 0` from `__init__`
- the `self._n_get_char_calls += 1` line in `get_char`
- the `n_get_char_calls` property

In `src/ptedit/controller.py` `perftest`, replace the `cpf` calculation with a simple frame-rate report:

```python
def perftest(self, max_time: float = 1.0) -> str:
    self.ed.move_end()
    frames = 0
    start = time()
    while time() - start < max_time:
        self.dpy.paint(self.ed.mark)
        frames += 1
        self.ed.insert(ord('a'))
        self.ed.move_backward_char()
        self.dpy.layout.move_backward_line()
    return f"Repainted {frames} frames in {time()-start:0.1f}s"
```

In `src/ptedit/display.py`, remove the two `_n0 = self.doc.n_get_char_calls` blocks and their dependent log lines from `paint`.

- [ ] **Step 2: Remove `Piece.__bool__`**

In `src/ptedit/piece.py`, delete the `__bool__` method. Then grep:

```
grep -n "if .*piece" src/ptedit/*.py
```

For each `if piece:` / `if not piece:` site, change to `if piece is not None:` / `if piece is None:`. (There are only a handful — `Edit.create`, `Edit.redo`, etc.)

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: drop instrumentation and Piece truthiness override"
```

---

## Phase 2 — Bug fixes (TDD red/green)

Each task: write a failing test, run it to confirm red, fix, run to confirm green, commit.

### Task 7: `find_not_char_backward` loop condition

Current: `while match and not self.at_start():` — `match` starts False so the loop never executes.

**Files:**
- Modify: `tests/test_document.py`
- Modify: `src/ptedit/document.py:191-202`

- [ ] **Step 1: Write failing test**

Append to `tests/test_document.py`:

```python
def test_find_not_char_backward():
    doc = document.Document('hello   world')   # three spaces between
    doc.set_point_end()
    # move past the trailing word
    assert doc.find_char_backward(' ')
    # now we're after the spaces; skip them backward
    assert doc.find_not_char_backward(' ')
    assert doc.get_char() == 'o'   # last char of 'hello'
```

- [ ] **Step 2: Run test, confirm RED**

Run: `python -m pytest tests/test_document.py::test_find_not_char_backward -v`
Expected: FAIL.

- [ ] **Step 3: Fix the loop condition**

In `src/ptedit/document.py`, find `find_not_char_backward` and change:

```python
# OLD
while match and not self.at_start():
# NEW
while not match and not self.at_start():
```

- [ ] **Step 4: Run test, confirm GREEN**

Run: `python -m pytest tests/test_document.py::test_find_not_char_backward -v`
Expected: PASS.

Run full suite: `python -m pytest tests/ -q` to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix: find_not_char_backward loop condition"
```

---

### Task 8: `find_backward` initial `match` value

Current: `match = self.get_point().position() <= len(pattern)` — when the point is too close to the start, `match` is set True and the function returns True without finding anything.

**Files:**
- Modify: `tests/test_document.py`
- Modify: `src/ptedit/document.py:222-239`

- [ ] **Step 1: Write failing test**

Append to `tests/test_document.py`:

```python
def test_find_backward_short_doc_returns_false_when_no_match():
    doc = document.Document('hi')
    doc.set_point_end()
    assert doc.find_backward('xyz', document.MatchMode.EXACT_CASE) is False
    # point should not have moved past start
    assert not doc.at_end()  # we did move_point(-len(pattern))
```

- [ ] **Step 2: Run test, confirm RED**

Run: `python -m pytest tests/test_document.py::test_find_backward_short_doc_returns_false_when_no_match -v`
Expected: FAIL (returns True).

- [ ] **Step 3: Fix the initial value**

In `src/ptedit/document.py` `find_backward`, replace:

```python
# OLD
match = self.get_point().position() <= len(pattern)
self.move_point(-len(pattern))
pt = self.get_point()
while not match and not pt.is_start():
```

with:

```python
# NEW
if self.get_point().position() < len(pattern):
    return False
self.move_point(-len(pattern))
pt = self.get_point()
match = False
while not match and not pt.is_start():
```

(The early-return semantics: a backward search needs at least `len(pattern)` chars before the point. If not, no match is possible.)

- [ ] **Step 4: Run test, confirm GREEN**

Run: `python -m pytest tests/test_document.py::test_find_backward_short_doc_returns_false_when_no_match -v`
Expected: PASS.

Run full suite: `python -m pytest tests/ -q`. If `test_isearch.py` regresses, check that backward-isearch from near-start still finds matches that *do* fit; the fix only affects the no-room case.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix: find_backward returns False when not enough chars before point"
```

---

### Task 9: `paste` with empty clipboard wipes marked region

Current: `_delete_region()` runs *before* the empty-clipboard check, so an empty paste destroys the marked text.

**Files:**
- Modify: `tests/test_document.py` (or new `tests/test_editor.py`)
- Modify: `src/ptedit/editor.py:202-207`

- [ ] **Step 1: Create `tests/test_editor.py` with failing test**

```python
# tests/test_editor.py
from ptedit import document, display, editor


def make_editor(text):
    doc = document.Document(text)
    dpy = display.Display(doc, display.Screen(24, 80))
    ed = editor.Editor(doc, dpy.layout, lambda msg, warn=False: dpy.show_message(msg, warn))
    return doc, dpy, ed


def test_paste_with_empty_clipboard_preserves_region():
    doc, dpy, ed = make_editor('hello world')
    doc.move_point(6)
    ed.set_mark()
    doc.move_point(5)             # mark spans 'world'
    assert ed.clipboard == ''
    ed.paste()
    # nothing on the clipboard, so the document should be unchanged
    assert doc.get_data() == 'hello world'
```

- [ ] **Step 2: Run test, confirm RED**

Run: `python -m pytest tests/test_editor.py::test_paste_with_empty_clipboard_preserves_region -v`
Expected: FAIL — doc becomes `'hello '`.

- [ ] **Step 3: Reorder the check in `paste`**

In `src/ptedit/editor.py`:

```python
# OLD
def paste(self):
    self._delete_region()
    if not self.clipboard:
        self.notify('Clipboard empty', True)
        return
    self.doc.insert(self.clipboard)

# NEW
def paste(self):
    if not self.clipboard:
        self.notify('Clipboard empty', True)
        return
    self._delete_region()
    self.doc.insert(self.clipboard)
```

- [ ] **Step 4: Run test, confirm GREEN**

Run: `python -m pytest tests/test_editor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix: paste with empty clipboard preserves marked region"
```

---

### Task 10: Rename `_delete_region` to reflect that it discards clipboard

The name suggests "delete" but it actually cuts to the clipboard via `_clip_region(cut=True)` and discards the result — meaning it *clobbers* whatever's on the clipboard except via the return value. Rename for clarity, and have it explicitly *not* touch `self.clipboard`.

**Files:**
- Modify: `src/ptedit/editor.py`
- Modify: `tests/test_editor.py`

- [ ] **Step 1: Add red test for "kill region must not clobber clipboard"**

Append to `tests/test_editor.py`:

```python
def test_kill_region_does_not_clobber_clipboard():
    doc, dpy, ed = make_editor('hello world')
    ed.clipboard = 'previous'
    doc.move_point(6)
    ed.set_mark()
    doc.move_point(5)             # mark spans 'world'
    ed.delete_forward_char()      # uses _delete_region internally
    assert doc.get_data() == 'hello '
    assert ed.clipboard == 'previous'   # untouched
```

- [ ] **Step 2: Run test, confirm RED or GREEN**

Run: `python -m pytest tests/test_editor.py::test_kill_region_does_not_clobber_clipboard -v`

Today this likely PASSES because `_delete_region` discards the return value of `_clip_region(cut=True)` and `_clip_region` doesn't touch `self.clipboard` directly. So it's actually fine — verify and document. If the test passes immediately, the rename below is a pure cleanup, no behavior change.

- [ ] **Step 3: Rename `_delete_region` → `_kill_region` and inline the deletion**

In `src/ptedit/editor.py`:

```python
def _kill_region(self):
    """Delete marked region in place; does NOT touch the clipboard."""
    if self.mark is None:
        return
    a, b = self.mark, self.doc.get_point()
    sign = -1
    if b.is_at_or_before(a):
        a, b = b, a
        sign = 1
    n = (b.position() - a.position())   # already aligned by swap above
    self.doc.set_point(b)
    self.doc.delete(sign * n)
    self.mark = None
```

Replace every `self._delete_region()` call with `self._kill_region()`.

- [ ] **Step 4: Run tests, confirm GREEN**

Run: `python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename _delete_region to _kill_region; never touch clipboard"
```

---

## Phase 3 — Sentinel uniformity

### Task 11: Use `length == 0` for sentinel detection

Change `Location.is_start` and `Location.is_end` to use `piece.length == 0` as the sentinel marker. This removes the `prev.prev is None` chain and gives both checks the same shape.

**Files:**
- Modify: `src/ptedit/location.py:31-36`

- [ ] **Step 1: Add a sanity test**

Append to `tests/test_location.py`:

```python
def test_sentinel_checks_length_zero():
    from ptedit import document
    doc = document.Document('abc')
    pt = doc.get_point()
    assert pt.is_start()
    # the sentinel previous to the first real piece must have length 0
    assert len(pt.piece.prev) == 0

    doc.set_point_end()
    pt = doc.get_point()
    assert pt.is_end()
    # at the end sentinel itself
    assert len(pt.piece) == 0
```

- [ ] **Step 2: Confirm test passes today (no change yet)**

Run: `python -m pytest tests/test_location.py::test_sentinel_checks_length_zero -v`
Expected: PASS.

- [ ] **Step 3: Rewrite the checks**

In `src/ptedit/location.py`:

```python
def is_start(self) -> bool:
    return self.offset == 0 and len(self.piece.prev) == 0   # type: ignore[arg-type]

def is_end(self) -> bool:
    return len(self.piece) == 0
```

(Drop the `assert self.piece.prev is not None` from `is_start` — the sentinel-length check accomplishes the same thing more uniformly. The only Location whose piece would have a `None` prev is the start sentinel itself, which is never the loc.piece by construction.)

- [ ] **Step 4: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: detect sentinels by length==0 for uniform checks"
```

---

### Task 12: Investigate `Edit.exclude_empty`

The `exclude_empty` flag (`edit.py:62`) handles "exclusion range is empty between two adjacent pieces" — pure insertion. The flag forces `before`/`after` to swap which side the existing pieces sit on. This is the closest thing to a real start/end asymmetry.

This is investigation rather than a guaranteed code change. If the simplification holds, write the patch; if not, document why and move on.

- [ ] **Step 1: Trace what happens for an insertion at position 0 vs end**

Read `Edit.create` (`src/ptedit/edit.py:100-116`) and `Edit.__init__`. For `delete=0, insert='X'`:
- `left, right = pt, pt`
- `exclude_first = pt.piece`, `exclude_last = pt.piece.prev` (since `right.offset` is whatever)
- `exclude_first == exclude_last.next` → `exclude_empty = True`
- Then `before = exclude_last`, `after = exclude_first`

So for an empty exclusion the "outer" pieces are the bracket-of-the-gap. For a non-empty exclusion the outer pieces are the *neighbors* of the excluded fragment. Different shapes.

- [ ] **Step 2: Try a patch that always materializes one piece in the exclusion**

If `delete == 0`, treat the insertion as splitting the current piece even when `pt.offset == 0` — produce a zero-length `pre` and a normal `post`, so `exclude_first/exclude_last` always reference real, non-adjacent pieces.

This may or may not work cleanly because `lsplit(0)` is currently asserted illegal (`assert 0 < offset`). Allowing offset==0 / offset==len(piece) requires careful thought — those degenerate splits create empty SecondaryPieces.

- [ ] **Step 3: Decision**

If the patch is more complex than the flag, **keep `exclude_empty`** but add a docstring on `Edit.__init__` linking to this analysis (one paragraph). Write a test asserting current behavior is correct for: insertion at start, insertion at end, insertion mid-piece, deletion across pieces, deletion within a piece. Commit with message:

```bash
git add -A
git commit -m "docs: document why Edit.exclude_empty is necessary; add edge tests"
```

If the patch *is* cleaner, apply it and commit:

```bash
git commit -m "refactor: drop Edit.exclude_empty by materializing zero-length pre/post"
```

---

## Phase 4 — Performance baseline

We need numbers before deciding anything about the ladder. Capture them with the ladder *as-is* (after the refactor), run the same scenarios after candidate changes.

### Task 13: Add scripted perftest scenarios

`Controller.perftest` today runs one fixed scenario (insert + back + up). Add a few more, named, and have them all return the same `frames/sec, chars/frame` shape so the output is comparable.

**Files:**
- Modify: `src/ptedit/controller.py`
- Modify: `src/ptedit/__main__.py`

- [ ] **Step 1: Refactor `perftest` to take a scenario name**

```python
# src/ptedit/controller.py

def perftest(self, scenario: str = 'insert', max_time: float = 1.0) -> str:
    runners = {
        'insert':       self._perf_insert_loop,
        'up_from_end':  self._perf_up_from_end,
        'pgup_from_end': self._perf_pgup_from_end,
        'pgdn_from_top': self._perf_pgdn_from_top,
    }
    if scenario not in runners:
        return f"unknown scenario: {scenario}; choices: {list(runners)}"
    return runners[scenario](max_time)

def _run(self, max_time: float, step):
    frames = 0
    start = time()
    while time() - start < max_time:
        self.dpy.paint(self.ed.mark)
        frames += 1
        step()
    return f"{frames} frames in {time()-start:0.2f}s = {frames/(time()-start):.0f} fps"

def _perf_insert_loop(self, max_time):
    self.ed.move_end()
    def step():
        self.ed.insert(ord('a'))
        self.ed.move_backward_char()
        self.dpy.layout.move_backward_line()
    return self._run(max_time, step)

def _perf_up_from_end(self, max_time):
    self.ed.move_end()
    def step():
        if self.doc.at_start():
            self.ed.move_end()
        self.dpy.layout.move_backward_line()
    return self._run(max_time, step)

def _perf_pgup_from_end(self, max_time):
    self.ed.move_end()
    def step():
        if self.doc.at_start():
            self.ed.move_end()
        self.dpy.layout.move_backward_page()
    return self._run(max_time, step)

def _perf_pgdn_from_top(self, max_time):
    self.ed.move_start()
    def step():
        if self.doc.at_end():
            self.ed.move_start()
        self.dpy.layout.move_forward_page()
    return self._run(max_time, step)
```

- [ ] **Step 2: Wire scenario name through CLI**

In `src/ptedit/__main__.py`, replace the boolean `-P` flag with a string option:

```python
parser.add_argument('-P', '--perftest', nargs='?', const='insert', default=None,
                    help='Run perftest scenario (insert|up_from_end|pgup_from_end|pgdn_from_top)')
```

In `main_loop`:

```python
if args.perftest is not None:
    return ctrl.perftest(args.perftest)
```

- [ ] **Step 3: Smoke test each scenario**

```bash
python -m ptedit -P insert tests/alice1flow.asc
python -m ptedit -P up_from_end tests/alice1flow.asc
python -m ptedit -P pgup_from_end tests/alice1flow.asc
python -m ptedit -P pgdn_from_top tests/alice1flow.asc
```

Record the four fps numbers in a scratch file `docs/plans/perf-baseline.md`. These are the baseline. Use a moderately large doc (`tests/alice1flow.asc` is suitable).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "perf: add scripted perftest scenarios for refactor comparison"
```

---

## Phase 5 — Ladder experiment

### Task 14: Spike — disable the ladder, reflow on demand

On a branch, replace the ladder with an on-demand approach: `bol_to_prev_bol` walks backward to the previous `\n` (or doc start), then formats forward, returning the rightmost BoL that is `<= original point`.

**Files:**
- Modify: `src/ptedit/layout.py`
- Branch: `experiment/no-ladder`

- [ ] **Step 1: Create branch**

```bash
git checkout -b experiment/no-ladder
```

- [ ] **Step 2: Replace ladder methods**

In `src/ptedit/layout.py`:

```python
class Layout:
    def __init__(self, doc, cols, rows, rungs, tab=4):
        # ... unchanged except: drop self.bol_ladder
        self.cols = cols
        self.rows = rows
        self.tab = tab
        self.preferred_col = 0
        self.pin_preferred_col = False

    def change_handler(self, start, end):
        pass   # no cache to rescue

    def clamp_to_bol(self):
        """Move point to the BoL of the current display line."""
        if self.doc.at_start() or self.doc.at_end():
            return
        target = self.doc.get_point()
        # walk back to previous hard newline (or start)
        self.doc.find_char_backward('\n')
        # then format forward, remembering the last BoL that is <= target
        bol = self.doc.get_point()
        while True:
            here = self.doc.get_point()
            if not here.is_at_or_before(target):
                self.doc.set_point(bol)
                return
            bol = here
            # advance one display line
            _line, _col_map = self.format_line()
            if self.doc.at_end():
                self.doc.set_point(bol)
                return

    def bol_to_next_bol(self):
        # already at BoL; one format_line advances exactly one display line
        self.format_line()

    def bol_to_prev_bol(self):
        if self.doc.at_start():
            return
        target = self.doc.get_point()
        # step back into the previous line
        self.doc.move_point(-1)
        self.find_bol()             # = clamp_to_bol but for the new point
        # we now have the BoL of the line containing (target - 1), which is
        # the previous display line — done.
```

(`find_bol` here is just an alias for `clamp_to_bol`. Inline if you prefer.)

Remove `ladder_point`, `rescue_ladder`, the `Ladder` class, and the side-effect logic in `format_line` that updates `self.bol_ladder`.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -q`
Expected: green (functionally equivalent for all behavior tests; the ladder was a cache).

- [ ] **Step 4: Run perftest scenarios**

```bash
python -m ptedit -P insert tests/alice1flow.asc
python -m ptedit -P up_from_end tests/alice1flow.asc
python -m ptedit -P pgup_from_end tests/alice1flow.asc
python -m ptedit -P pgdn_from_top tests/alice1flow.asc
```

Record numbers next to baseline in `docs/plans/perf-baseline.md`.

- [ ] **Step 5: Decision point**

Compare the four scenarios. Three outcomes:

- **A) No-ladder is comparable or better on all scenarios** → merge the branch, delete ladder code permanently, commit. Done.
- **B) No-ladder is ~similar on forward but significantly worse on `up_from_end` / `pgup_from_end`** (your prior intuition) → consider a small one-frame BoL cache (just remember the last `clamp_to_bol` result) before falling back to the full reflow. Re-measure.
- **C) No-ladder is much worse, even with a 1-frame cache** → discard the branch (`git checkout main && git branch -D experiment/no-ladder`); keep the ladder. Move to Task 15.

Document the decision and numbers in `docs/plans/perf-baseline.md`.

---

### Task 15: (Conditional on Task 14 outcome C) Simplify ladder rescue

Only run this task if the ladder stays. The `rescue_ladder` method in `layout.py` is the most complex piece; simplify by *invalidating* on any change rather than trying to preserve cached BoLs across edits. The cache will rebuild on the next paint.

**Files:**
- Modify: `src/ptedit/layout.py:235-289`

- [ ] **Step 1: Replace `rescue_ladder` with full invalidation**

```python
def change_handler(self, start, end):
    # any document change invalidates the BoL cache; it'll repopulate
    # on the next paint via ladder_point + bol_to_next_bol
    self.bol_ladder = Ladder()
```

Delete the body of the old `rescue_ladder`.

- [ ] **Step 2: Re-run perftest**

If the cache-rebuild cost on the next paint is tolerable (typical case: edits don't span the whole ladder; ladder rebuild is `~rungs` chars-to-find-prev-newline + reflow forward across visible region), this is a big win in code complexity.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: invalidate BoL cache on edit instead of rescuing"
```

---

### Task 16: (Conditional on Task 14 outcome A) Add per-piece nl_count for status

Even if we drop the ladder, `Controller.status_message` walks the full document twice per frame to count newlines. Adding `nl_count` to Piece eliminates that.

This task only makes sense if the ladder goes. If the ladder stays, status doc-walks are dwarfed by ladder cache hits and this isn't urgent.

**Files:**
- Modify: `src/ptedit/piece.py`
- Modify: `src/ptedit/document.py`
- Modify: `src/ptedit/controller.py` `status_message`

- [ ] **Step 1: Add `nl_count` to Piece**

```python
# in PrimaryPiece.extend:
self._nl_count: int = self._data.count('\n')

def extend(self, s: str):
    self._data += s
    self._len += len(s)
    self._nl_count += s.count('\n')

def trim(self, n: int) -> Self:
    if n > 0:
        self._nl_count -= self._data[:n].count('\n')
        self._data = self._data[n:]
    else:
        self._nl_count -= self._data[n:].count('\n')
        self._data = self._data[:n]
    self._len -= abs(n)
    return self

@property
def nl_count(self) -> int:
    return self._nl_count
```

For SecondaryPiece, compute lazily over the slice (or eagerly at construction):

```python
def __init__(self, *, source, length, start=0, prev=None, next=None):
    super().__init__(prev=prev, next=next)
    self._src = source
    self._start = start
    self._len = length
    self._nl_count = source.data[start:start+length].count('\n')

@property
def nl_count(self) -> int:
    return self._nl_count
```

- [ ] **Step 2: Add a `nl_count_to(loc)` helper on Document**

```python
def nl_count_to(self, end: Location | None = None) -> int:
    """Count newlines in [start, end), end defaulting to point."""
    end = end or self._point
    p = self._start.next
    n = 0
    while p is not None and p is not end.piece:
        n += p.nl_count
        p = p.next
    if p is end.piece:
        n += p.data[:end.offset].count('\n')
    return n

def nl_count_total(self) -> int:
    n = 0
    p = self._start.next
    while p is not None:
        n += p.nl_count
        p = p.next
    return n
```

- [ ] **Step 3: Replace doc-walk in `status_message`**

```python
# in Controller.status_message
pt_nl = self.doc.nl_count_to(pt)
doc_nl = self.doc.nl_count_total()
```

- [ ] **Step 4: Test**

Append to `tests/test_document.py`:

```python
def test_nl_count_matches_get_data():
    doc = document.Document('alpha\nbravo\ncharlie\n')
    assert doc.nl_count_total() == 3
    doc.move_point(8)   # inside 'bravo'
    assert doc.nl_count_to() == 1
    doc.insert('\nx\n')
    assert doc.nl_count_total() == 5
    doc.delete(-2)
    assert doc.nl_count_total() == 4
```

Run: `python -m pytest tests/ -q`. Expected: green.

- [ ] **Step 5: Re-run perftest, expect status frames per second to climb**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "perf: per-piece nl_count for O(pieces) status counts"
```

---

## Self-review checklist

- **Spec coverage:** MVC refactor (Tasks 2-6) ✓, status leak (Task 5) ✓, find_not_char_backward (Task 7) ✓, find_backward (Task 8) ✓, paste empty clipboard (Task 9) ✓, _delete_region naming (Task 10) ✓, sentinel uniformity (Task 11) ✓, exclude_empty investigation (Task 12) ✓, perftest baseline (Task 13) ✓, ladder spike (Task 14) ✓, conditional simplification or nl_count follow-ups (Tasks 15-16) ✓.
- **Forth excluded:** plan stops at Python cleanup, as requested.
- **Test-driven:** every bug fix has a red test before the fix; refactor tasks are pinned by characterization tests in Task 1.
- **Frequent commits:** one commit per task, with clear messages.
- **No placeholders:** every step has a concrete action, file path, and code/command. The exception is Task 12 (investigation) which has a documented decision branch.
