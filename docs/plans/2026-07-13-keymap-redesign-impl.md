# Keymap Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the union-typed, three-namespace key-dispatch in `controller.py`
with a named command registry, three declarative `Mode` records, and a small
mode-stack dispatcher — plus a derived help overlay.

**Architecture:** Commands become a flat `dict[str, Callable[[], None]]` (name is
the documentation; Forth name→xt shape). Each `Mode` is `{name, bindings:
dict[int,str], on_unbound, transient}`. Modes form a stack; the dispatcher looks
up a key's command name, else calls the mode's `on_unbound` (which may decline →
pop and re-dispatch). Editor gains six delegations so all buffer commands live
under `ed`. Help renders from the registry into a status-bar-preserving overlay.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `curses` (for key constants only in
tests). Branch: `keymap-redesign` (off `main`).

## Global Constraints

- Behavior-preserving refactor of dispatch: every current key does what it does
  today (see design §"Behavior preservation"). `uv run pytest` green after every
  task; golden render tests byte-identical (dispatch doesn't touch the render
  path). New behavior added only in Task 4 (help screen + error hint).
- Design source of truth: `docs/plans/2026-07-13-keymap-redesign-design.md`.
- Commands are a plain `dict[str, Callable[[], None]]` — no wrapper class, no
  help string. Names default from the function `__name__`, kebab-cased.
- Command references are **strings**; mode references are the **`KeyMode` enum**.
- The unbound-key field is named **`on_unbound`** (never `default`); typed
  `(int) -> bool` returning **handled?**.
- Mode lifetime is a **stack** with a `transient` pop-after-one flag.
- No compound-action type: a compound is a closure/method that calls other
  commands. Delete `Action`, `Actionable`, `actionlist`, and the old `KeyMode`
  int-in-dict / `'fallback'` / `'after'` machinery.
- Facade **delegates**, does not relocate, Layout's line/page methods.
- Commit style: repo convention, ending with
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File structure

| File | Responsibility after this plan |
|------|--------------------------------|
| `src/ptedit/editor.py` | Buffer-command namespace: adds six line/page delegations to Layout (Task 1). |
| `src/ptedit/controller.py` | `keyname` helper (Task 2); command registry, `Mode`, mode stack, dispatcher (Task 3); help overlay wiring, error hint (Task 4). |
| `src/ptedit/display.py` | Adds `show_overlay` (Task 4). |
| `tests/test_editor.py` | Existing isearch characterization stays; facade + dispatch-mechanic tests added. |
| `tests/test_controller.py` | New: `keyname`, registry completeness, mode mechanics, help (Tasks 2–4). |

---

### Task 1: Editor facade — line/page commands under `ed`

**Files:**
- Modify: `src/ptedit/editor.py:36-37` (end of `Editor.__init__` state block)
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: `Layout.move_start_line`, `move_end_line`, `move_forward_line`,
  `move_backward_line`, `move_forward_page`, `move_backward_page` (all `() -> None`).
- Produces: `Editor.move_start_line`, `Editor.move_end_line`,
  `Editor.move_forward_line`, `Editor.move_backward_line`,
  `Editor.move_forward_page`, `Editor.move_backward_page` — each a bound
  reference to the identically-named `Layout` method (`() -> None`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_editor.py`:

```python
def test_editor_delegates_line_and_page_moves_to_layout():
    from ptedit import editor as editor_mod
    doc = document.Document('abcdef\nghijkl\nmnopqr\n')
    dpy = display.Display(doc, display.Screen(24, 16))
    ed = editor_mod.Editor(doc, dpy.layout, lambda msg, warn=False: None)
    # each delegation is the very same bound method object as Layout's
    for name in ('move_start_line', 'move_end_line', 'move_forward_line',
                 'move_backward_line', 'move_forward_page', 'move_backward_page'):
        assert getattr(ed, name).__func__ is getattr(dpy.layout, name).__func__
    # and it actually moves the point through Layout
    doc.set_point_start()
    ed.move_forward_line()
    assert doc.get_point().position() == 7        # BoL of line 1
```

(`tests/test_editor.py` already imports `document` and `display`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_editor.py::test_editor_delegates_line_and_page_moves_to_layout -v`
Expected: FAIL — `AttributeError: 'Editor' object has no attribute 'move_start_line'`.

- [ ] **Step 3: Add the delegations**

In `src/ptedit/editor.py`, at the end of `__init__` (after
`self.match_mode: MatchMode = MatchMode.SMART_CASE`):

```python
        # Facade: line/page motion is a buffer command, exposed under `ed`.
        # The mechanism (ladder, goal column) stays in Layout — this delegates,
        # it does not relocate.
        self.move_start_line = layout.move_start_line
        self.move_end_line = layout.move_end_line
        self.move_forward_line = layout.move_forward_line
        self.move_backward_line = layout.move_backward_line
        self.move_forward_page = layout.move_forward_page
        self.move_backward_page = layout.move_backward_page
```

- [ ] **Step 4: Run the test and the full suite**

Run: `uv run pytest tests/test_editor.py::test_editor_delegates_line_and_page_moves_to_layout -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass (90 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/ptedit/editor.py tests/test_editor.py
git commit -m "refactor(editor): expose line/page motion under ed (delegates to Layout)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `keyname` — key code → display string

**Files:**
- Modify: `src/ptedit/controller.py` (add module-level `keyname` near `ctrl`, ~line 42)
- Test: `tests/test_controller.py` (new file)

**Interfaces:**
- Produces: `controller.keyname(code: int) -> str` — human label for a key code.
  Control codes `0..31` → `"C-<L>"` (e.g. `9 → "C-I"`); named specials
  (`27 → "Esc"`, `32 → "Space"`, `127 → "Del"`, and the curses arrow/enter/
  backspace codes) → their word; printables `33..126` → the character;
  anything else → `"<code>"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_controller.py`:

```python
import curses

from ptedit import controller


def test_keyname_formats_codes():
    assert controller.keyname(ord('a')) == 'a'
    assert controller.keyname(ord('?')) == '?'
    assert controller.keyname(9) == 'C-I'          # tab is control-I
    assert controller.keyname(1) == 'C-A'
    assert controller.keyname(27) == 'Esc'
    assert controller.keyname(32) == 'Space'
    assert controller.keyname(127) == 'Del'
    assert controller.keyname(curses.KEY_LEFT) == 'Left'
    assert controller.keyname(curses.KEY_ENTER) == 'Enter'
    assert controller.keyname(999999) == '<999999>'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_controller.py::test_keyname_formats_codes -v`
Expected: FAIL — `AttributeError: module 'ptedit.controller' has no attribute 'keyname'`.

- [ ] **Step 3: Implement `keyname`**

In `src/ptedit/controller.py`, immediately after the `ctrl` function:

```python
# Codes with a nicer label than the raw control-chord / character.
_KEYNAMES: dict[int, str] = {
    27: 'Esc', 32: 'Space', 127: 'Del',
    curses.KEY_LEFT: 'Left', curses.KEY_RIGHT: 'Right',
    curses.KEY_UP: 'Up', curses.KEY_DOWN: 'Down',
    curses.KEY_ENTER: 'Enter', curses.KEY_BACKSPACE: 'Bksp',
}


def keyname(code: int) -> str:
    """Human-readable label for a key code, for help and error messages."""
    if code in _KEYNAMES:
        return _KEYNAMES[code]
    if 0 <= code < 32:
        return 'C-' + chr(code | 0x40)      # 9 -> 'C-I'
    if 32 < code < 127:
        return chr(code)
    return f'<{code}>'
```

- [ ] **Step 4: Run the test and the full suite**

Run: `uv run pytest tests/test_controller.py::test_keyname_formats_codes -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/ptedit/controller.py tests/test_controller.py
git commit -m "feat(controller): keyname helper for key-code display labels

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Command registry, Mode stack, and dispatcher

**Files:**
- Modify: `src/ptedit/controller.py` — replace `Action`/`Actionable`/`actionlist`
  (`45-57`), the `self.keymap` build (`82-150`), and `dispatch`/`_act`
  (`266-297`); extend `KeyMode` (`20-23`).
- Test: `tests/test_controller.py`, and existing `tests/test_editor.py` (must stay green).

**Interfaces:**
- Consumes: `controller.keyname` (Task 2); `Editor` buffer commands incl. the
  Task 1 delegations; `Display.recenter`, `Display.show_message(msg, warn)`.
- Produces:
  - `controller.Mode` dataclass: `name: KeyMode`, `bindings: dict[int, str]`,
    `on_unbound: Callable[[int], bool]`, `transient: bool = False`.
  - `Controller.commands: dict[str, Callable[[], None]]` — the registry.
  - `Controller.modes: dict[KeyMode, Mode]`; `Controller.stack: list[Mode]`
    (runtime, initialized `[modes[KeyMode.NORMAL]]`).
  - `Controller._register(fn, name=None) -> str`; `Controller._push(m: KeyMode)`,
    `Controller._pop()`; `Controller.dispatch(key: int) -> None`.
  - `KeyMode` gains no new member in this task (HELP is added in Task 4).

- [ ] **Step 1: Write the failing mechanic tests**

Append to `tests/test_controller.py`:

```python
from ptedit.screen import Screen


def _ctrl(tmp_path, text='hello world\n'):
    f = tmp_path / 't.txt'
    f.write_text(text)
    return controller.Controller(str(f), Screen(24, 80))


def test_registry_covers_every_binding(tmp_path):
    c = _ctrl(tmp_path)
    for mode in c.modes.values():
        for key, name in mode.bindings.items():
            assert name in c.commands, f'{mode.name.name}:{name} unregistered'


def test_normal_printable_self_inserts(tmp_path):
    c = _ctrl(tmp_path, '')
    c.dispatch(ord('x'))
    assert c.doc.get_data() == 'x'
    assert c.stack[-1].name is controller.KeyMode.NORMAL


def test_isearch_printable_extends_search(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('S'))
    assert c.stack[-1].name is controller.KeyMode.ISEARCH
    for ch in 'world':
        c.dispatch(ord(ch))
    assert c.ed.isearch_text == 'world'
    assert c.doc.get_data() == 'hello world\n'         # nothing inserted


def test_isearch_unbound_key_exits_and_re_dispatches(tmp_path):
    # An arrow in isearch exits search (leaving point) AND performs the motion.
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('S'))
    for ch in 'world':
        c.dispatch(ord(ch))
    pos = c.doc.get_point().position()                 # after the 'world' match
    c.dispatch(curses.KEY_LEFT)                         # unbound in ISEARCH
    assert c.ed.isearch_dir is None                    # search exited
    assert c.stack[-1].name is controller.KeyMode.NORMAL
    assert c.doc.get_point().position() == pos - 1     # motion happened


def test_meta_is_one_shot(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                   # enter META
    assert c.stack[-1].name is controller.KeyMode.META
    c.dispatch(ord('m'))                               # set-mark
    assert c.ed.mark is not None
    assert c.stack[-1].name is controller.KeyMode.NORMAL   # auto-returned


def test_meta_unknown_key_returns_to_normal(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))
    c.dispatch(ord('Z'))                               # unbound in META
    assert c.stack[-1].name is controller.KeyMode.NORMAL
    assert 'No action' in c.dpy.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_controller.py -k "registry or printable or isearch or meta" -v`
Expected: FAIL — `Controller` has no `modes`/`commands`/`stack` yet (AttributeError).

- [ ] **Step 3: Extend `KeyMode` and add the `Mode` dataclass**

In `src/ptedit/controller.py`, the `KeyMode` enum stays as-is for this task:

```python
class KeyMode(IntEnum):
    NORMAL = 0
    ISEARCH = 1
    META = 2
```

Delete `ActionFn`, `Action`, `Actionable`, `ActionKey`, and `actionlist`
(lines 45-57). In the imports, add `from dataclasses import dataclass` and drop
the now-unused `Literal` and `cast` (they were only used by the deleted
`ActionKey`/`actionlist`) — change `from typing import Callable, Literal, cast`
to `from typing import Callable`. Then add, after `keyname`:

```python
@dataclass
class Mode:
    name: KeyMode
    bindings: dict[int, str]                  # key code -> command name
    on_unbound: Callable[[int], bool]         # unbound key: returns handled?
    transient: bool = False                   # prefix mode: pop after one dispatch
```

- [ ] **Step 4: Replace the keymap build with registry + modes**

Replace the `self.keymap = [...]` block (lines 82-150) in `__init__` with:

```python
        self.commands: dict[str, Callable[[], None]] = {}
        ed = self.ed
        dpy = self.dpy

        # buffer commands (auto-named from __name__, kebab-cased)
        for fn in (
            ed.move_backward_char, ed.move_forward_char,
            ed.move_backward_word, ed.move_forward_word,
            ed.move_backward_para, ed.move_forward_para,
            ed.move_start_line, ed.move_end_line,
            ed.move_forward_line, ed.move_backward_line,
            ed.move_forward_page, ed.move_backward_page,
            ed.move_start, ed.move_end,
            ed.delete_backward_char, ed.delete_forward_char,
            ed.set_mark, ed.clear_mark,
            ed.copy, ed.cut, ed.paste, ed.copy_line, ed.cut_line,
            ed.undo, ed.redo, ed.squash, ed.toggle_overwrite,
            ed.isearch_forward, ed.isearch_backward, ed.isearch_delete,
        ):
            self._register(fn)

        # app / view commands
        self._register(dpy.recenter)
        self._register(self.save)
        self._register(self.quit)

        # closures & composites (explicit names)
        self._register(lambda: ed.insert(ord('\t')), 'insert-tab')
        self._register(lambda: ed.insert(ord('\n')), 'insert-newline')
        self._register(self._enter_meta, 'enter-meta')
        self._register(self._search_forward, 'search-forward')
        self._register(self._search_backward, 'search-backward')
        self._register(self._isearch_cancel, 'isearch-cancel')

        self.modes: dict[KeyMode, Mode] = {
            KeyMode.NORMAL: Mode(KeyMode.NORMAL, {
                curses.KEY_LEFT: 'move-backward-char',
                curses.KEY_RIGHT: 'move-forward-char',
                curses.KEY_UP: 'move-backward-line',
                curses.KEY_DOWN: 'move-forward-line',
                curses.KEY_ENTER: 'insert-newline',
                curses.KEY_BACKSPACE: 'delete-backward-char',
                127: 'delete-backward-char',
                ctrl('A'): 'move-start-line',
                ctrl('B'): 'move-backward-word',
                ctrl('F'): 'move-forward-word',
                ctrl('E'): 'move-end-line',
                ctrl('D'): 'delete-forward-char',
                ctrl('I'): 'insert-tab',
                ctrl('J'): 'insert-newline',
                ctrl('L'): 'recenter',
                ctrl('Y'): 'redo',
                ctrl('Z'): 'undo',
                ctrl('['): 'enter-meta',
                ctrl('_'): 'squash',
                ctrl('S'): 'search-forward',
                ctrl('R'): 'search-backward',
                ctrl('O'): 'toggle-overwrite',
            }, on_unbound=self._normal_unbound),
            KeyMode.ISEARCH: Mode(KeyMode.ISEARCH, {
                ctrl('S'): 'isearch-forward',
                ctrl('R'): 'isearch-backward',
                ctrl('['): 'isearch-cancel',
                127: 'isearch-delete',
            }, on_unbound=self._isearch_unbound),
            KeyMode.META: Mode(KeyMode.META, {
                ctrl('['): 'clear-mark',
                ord('a'): 'move-backward-page',
                ord('b'): 'move-backward-para',
                ord('f'): 'move-forward-para',
                ord('e'): 'move-forward-page',
                ord('A'): 'move-start',
                ord('E'): 'move-end',
                ord('m'): 'set-mark',
                ord('s'): 'save',
                ord('q'): 'quit',
                ord('c'): 'copy',
                ord('k'): 'cut-line',
                ord('K'): 'copy-line',
                ord('x'): 'cut',
                ord('v'): 'paste',
                ord('y'): 'redo',
                ord('z'): 'undo',
            }, on_unbound=self._meta_unbound, transient=True),
        }
        self.stack: list[Mode] = [self.modes[KeyMode.NORMAL]]

        # startup validation: every bound name resolves (also the future
        # YAML-config validator).
        for mode in self.modes.values():
            for key, name in mode.bindings.items():
                assert name in self.commands, \
                    f'{mode.name.name}: {keyname(key)} -> unknown command {name!r}'
```

Delete the now-unused `self.mode = KeyMode.NORMAL` line (line 62) — the stack
replaces it — and the `printable = {...}` line (83).

- [ ] **Step 5: Add the helper + handler methods and the new `dispatch`**

Replace `dispatch` and `_act` (lines 266-297) with:

```python
    def _register(self, fn: Callable[[], None], name: str | None = None) -> str:
        name = name or fn.__name__.replace('_', '-')
        self.commands[name] = fn
        return name

    def _push(self, m: KeyMode) -> None:
        self.stack.append(self.modes[m])

    def _pop(self) -> None:
        assert len(self.stack) > 1, "cannot pop the base mode"
        self.stack.pop()

    def _enter_meta(self) -> None:
        self._push(KeyMode.META)

    def _search_forward(self) -> None:
        self._push(KeyMode.ISEARCH)
        self.ed.isearch_forward()

    def _search_backward(self) -> None:
        self._push(KeyMode.ISEARCH)
        self.ed.isearch_backward()

    def _isearch_cancel(self) -> None:
        self.ed.isearch_cancel()
        self._pop()

    def _beep(self, key: int) -> None:
        self.dpy.show_message(
            f'No action for {keyname(key)} in {self.stack[-1].name.name}', True)

    def _normal_unbound(self, key: int) -> bool:
        if 32 <= key < 127:
            self.ed.insert(key)
        else:
            self._beep(key)
        return True

    def _isearch_unbound(self, key: int) -> bool:
        if 32 <= key < 127:
            self.ed.isearch_insert(chr(key))
            return True
        self.ed.isearch_exit()
        return False

    def _meta_unbound(self, key: int) -> bool:
        self._beep(key)
        return True

    def dispatch(self, key: int) -> None:
        """Route one key through the current mode."""
        mode = self.stack[-1]
        name = mode.bindings.get(key)
        if name:
            self.commands[name]()
        elif not mode.on_unbound(key):        # declined -> pop and re-dispatch below
            self.stack.pop()
            return self.dispatch(key)
        if mode.transient and self.stack[-1] is mode:
            self.stack.pop()
```

Note ordering: `_register`, `_push`, `_pop`, `_enter_meta`, `_search_*`,
`_isearch_cancel`, and the `_*_unbound` handlers must be defined on the class
(they are referenced during `__init__` only as bound-method objects, so their
definition order in the file doesn't matter — put them wherever reads cleanly,
e.g. just above `dispatch`).

- [ ] **Step 6: Fix the interactive loop's mode reference**

`interactive` (lines 177-195) does not reference `self.mode`; leave it. But
confirm no other code reads `self.mode` — search and fix:

Run: `grep -n "self\.mode\b" src/ptedit/controller.py`
Expected: no matches (the old `self.mode` attribute is gone). If any remain,
replace a read of the current mode with `self.stack[-1].name`.

- [ ] **Step 7: Run the new tests, the isearch characterization, and the full suite**

Run: `uv run pytest tests/test_controller.py tests/test_editor.py -v`
Expected: PASS, including the existing
`test_isearch_keys_route_to_search_not_document`.
Run: `uv run pytest -q`
Expected: all pass; golden render tests unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/ptedit/controller.py tests/test_controller.py
git commit -m "refactor(controller): named command registry + mode stack dispatch

Replaces the Actionable union and 'fallback'/'after' magic keys with a
dict[str, callable] registry, three declarative Mode records, and a
~12-line stack dispatcher. on_unbound is each mode's one unbound-key
strategy; transient marks the META prefix.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Help overlay, HELP mode, and the help-key error hint

**Files:**
- Modify: `src/ptedit/display.py` (add `show_overlay`)
- Modify: `src/ptedit/controller.py` (`KeyMode.HELP`, `describe_bindings`,
  `_help_lines`, `_chord_for`, hint in `_beep`, `interactive` paints overlay in
  HELP, register + bind `describe-bindings`, add HELP mode)
- Test: `tests/test_controller.py`, `tests/test_display.py`

**Interfaces:**
- Consumes: everything from Task 3; `keyname`.
- Produces:
  - `Display.show_overlay(lines: list[str]) -> None` — paints `lines` into the
    text region (rows `0..rows-1`), padded/truncated to `cols`; leaves the
    status row (`rows`) untouched.
  - `KeyMode.HELP = 3`; `Controller.describe_bindings()`,
    `Controller._help_lines() -> list[str]`,
    `Controller._chord_for(command_name: str) -> str | None`.
  - `_beep` message gains a trailing ` — <chord> for help` when a chord exists.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_display.py` (it already has `GridScreen` with `chars`/`hi`
grids from earlier tasks):

```python
def test_show_overlay_preserves_status_row():
    doc = document.Document('body text\n' * 30)
    scr = GridScreen(24, 80)
    dpy = display.Display(doc, scr)
    dpy.paint(None)
    # stamp a sentinel on the status row (row == dpy.rows) to prove it survives
    scr.move(dpy.rows, 0)
    scr.put(ord('#'))
    dpy.show_overlay(['HELP LINE ONE', 'HELP LINE TWO'])
    assert ''.join(chr(c) for c in scr.chars[0]).startswith('HELP LINE ONE')
    assert scr.chars[dpy.rows][0] == ord('#')        # status row untouched
```

Append to `tests/test_controller.py`:

```python
def test_help_shows_and_dismisses(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                  # META
    c.dispatch(ord('?'))                              # describe-bindings
    assert c.stack[-1].name is controller.KeyMode.HELP
    lines = c._help_lines()
    assert any('move-forward-char' in ln for ln in lines)
    c.dispatch(ord('x'))                              # any key dismisses
    assert c.stack[-1].name is controller.KeyMode.NORMAL
    assert c.doc.get_data() == 'hello world\n'        # dismiss key not inserted


def test_unbound_error_names_help_chord(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('G'))                  # C-G: unbound in NORMAL
    assert 'No action' in c.dpy.message
    assert 'Esc ? for help' in c.dpy.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_display.py::test_show_overlay_preserves_status_row tests/test_controller.py -k "help or chord" -v`
Expected: FAIL — `Display` has no `show_overlay`; `KeyMode` has no `HELP`;
error message lacks the hint.

- [ ] **Step 3: Add `Display.show_overlay`**

In `src/ptedit/display.py`, add a method to `Display`:

```python
    def show_overlay(self, lines: list[str]) -> None:
        """Paint `lines` over the text region only; leave the status row intact."""
        for r in range(self.rows):
            self.scr.move(r, 0)
            text = (lines[r] if r < len(lines) else '')[:self.cols]
            self.scr.puts(text + ' ' * (self.cols - len(text)))
```

- [ ] **Step 4: Add HELP mode, describe-bindings, help lines, and the chord lookup**

In `src/ptedit/controller.py`, extend the enum:

```python
class KeyMode(IntEnum):
    NORMAL = 0
    ISEARCH = 1
    META = 2
    HELP = 3
```

Register and bind describe-bindings. In `__init__`, add to the closures block:

```python
        self._register(self.describe_bindings, 'describe-bindings')
```

Add `ord('?'): 'describe-bindings'` to the `KeyMode.META` bindings dict. Add a
HELP mode to `self.modes` (empty bindings; any key pops it):

```python
            KeyMode.HELP: Mode(KeyMode.HELP, {}, on_unbound=self._help_unbound),
```

Add the methods (near the other handlers):

```python
    def _help_unbound(self, key: int) -> bool:
        self._pop()                       # any key dismisses the overlay
        return True

    def describe_bindings(self) -> None:
        if self.stack[-1].transient:      # leave the META prefix we arrived through
            self._pop()
        self._push(KeyMode.HELP)

    def _help_lines(self) -> list[str]:
        out: list[str] = []
        for km in (KeyMode.NORMAL, KeyMode.META, KeyMode.ISEARCH):
            mode = self.modes[km]
            out.append(f'-- {km.name} --')
            for key in sorted(mode.bindings):
                out.append(f'  {keyname(key):<8} {mode.bindings[key]}')
        return out

    def _chord_for(self, command_name: str) -> str | None:
        """Key chord that invokes `command_name`, e.g. 'Esc ?'. Handles a direct
        NORMAL binding and a binding inside a prefix mode reached from NORMAL."""
        normal = self.modes[KeyMode.NORMAL]
        for key, name in normal.bindings.items():
            if name == command_name:
                return keyname(key)
        for mode in self.modes.values():
            if mode.name is KeyMode.NORMAL:
                continue
            for key, name in mode.bindings.items():
                if name != command_name:
                    continue
                enter = next((keyname(k) for k, n in normal.bindings.items()
                              if n == f'enter-{mode.name.name.lower()}'), None)
                return f'{enter} {keyname(key)}' if enter else keyname(key)
        return None
```

Note `_chord_for` relies on the convention that a prefix mode `X` is entered by a
command named `enter-<x>` (here `enter-meta`). This holds for META.

- [ ] **Step 5: Add the hint to `_beep`**

Replace `_beep` from Task 3 with:

```python
    def _beep(self, key: int) -> None:
        hint = self._chord_for('describe-bindings')
        suffix = f' — {hint} for help' if hint else ''
        self.dpy.show_message(
            f'No action for {keyname(key)} in {self.stack[-1].name.name}{suffix}',
            True)
```

- [ ] **Step 6: Paint the overlay while in HELP**

In `interactive` (lines 177-195), replace the paint at the top of the loop so
HELP paints the overlay instead of the buffer, keeping the status line in both:

```python
    def interactive(self) -> None:
        while self.active:
            if self.stack[-1].name is KeyMode.HELP:
                self.dpy.show_overlay(self._help_lines())
                cursor = Cell(0, 0)
            else:
                cursor = self.dpy.paint(self.ed.mark)
            self.dpy.scr.move(self.dpy.rows, 0)
            status = self.status_message(cursor)
            status = (status[:self.dpy.cols] if len(status) >= self.dpy.cols
                      else status + ' ' * (self.dpy.cols - len(status)))
            self.dpy.scr.puts(status, highlight=True)
            self.dpy.scr.move(*cursor)
            self.dpy.scr.refresh()
            try:
                assert self.getch, "interactive() requires a getch function"
                key = self.getch()
                logging.info(f'key ${key:02x}')
                self.dispatch(key)
                if self.doc.dirty:
                    self.autosave()
            except KeyboardInterrupt:
                self.quit()
```

(`Cell` is already imported in `controller.py`.)

- [ ] **Step 7: Run the new tests and the full suite**

Run: `uv run pytest tests/test_display.py::test_show_overlay_preserves_status_row tests/test_controller.py -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass; golden render tests byte-identical.

- [ ] **Step 8: Manual smoke check (optional but recommended)**

Run: `uv run python -m ptedit /tmp/keymap-smoke.txt` (create the file first with
`printf 'hello\nworld\n' > /tmp/keymap-smoke.txt`). Verify: typing inserts; arrows
move; `Esc ?` shows the binding list with the status bar intact; any key returns;
`C-G` shows `No action for C-G in NORMAL — Esc ? for help`; `Esc q` quits.

- [ ] **Step 9: Commit**

```bash
git add src/ptedit/display.py src/ptedit/controller.py tests/test_display.py tests/test_controller.py
git commit -m "feat(controller): help overlay derived from the command registry

Esc ? lists bindings over the text area (status bar preserved); any key
dismisses. The no-action error now names the live help chord.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Deferred (seams left, not built)

Per the design: the external YAML keymap file + `--keymap` overlay, and keyboard
macro record/replay. `bindings` is already `dict[int, str]` and the startup loop
is already the validator; a loader is a small follow-up plan, not part of this one.

## Self-review notes

- **Spec coverage:** registry (§1) → Task 3; Mode/stack/dispatcher (§2–3) → Task 3;
  facade (§4) → Task 1; help overlay + status-bar preservation (§5) → Task 4;
  startup validation (§6) → Task 3 Step 4; error names help key → Task 4; `keyname`
  → Task 2; behavior-preservation list → Task 3 tests + existing characterization.
  Deferred items → documented, not built.
- **Command coverage vs current keymap:** every current binding maps to a
  registered command (arrows, enter, backspace/127, C-A/B/F/E/D/I/J/L/Y/Z/[/_/S/R/O,
  all META letters, all ISEARCH keys). Bare-int self-inserts (C-I/C-J/KEY_ENTER)
  become `insert-tab`/`insert-newline`; printable self-insert moves to
  `on_unbound`.
- **Type consistency:** `on_unbound: (int) -> bool` everywhere; commands are
  zero-arg callables invoked `self.commands[name]()`; mode refs are `KeyMode`;
  `_push` takes `KeyMode`, `stack` holds `Mode`.
