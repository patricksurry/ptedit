# Keymap Redesign — Design

**Status:** approved design, pre-implementation.
**Scope:** `src/ptedit/controller.py` (keymap + dispatch), small additions to
`src/ptedit/editor.py` (facade) and `src/ptedit/display.py` (help overlay).
No change to the model, layout, or rendering pipeline.

## Motivation

The current key dispatch (`controller.py:45-297`) works but its *shape* leaks
mechanism and carries three awkward constructs:

- **Three-namespace bindings.** Keys bind to `ed.*`, `layout.*`, and `dpy.*`
  directly, so the table exposes *which layer implements a command* rather than
  *what the command is*. In the eventual 6502 Forth port words have no owner —
  this is a Python-namespacing artifact.
- **A union-typed action.** `Actionable = None | KeyMode | int | ActionFn |
  list[...]` plus `actionlist`/`cast` plumbing: a binding value can be a mode
  switch, a self-inserted byte, a callable, or a list of these.
- **Magic string keys.** `'fallback'` (ISEARCH retries unknown keys in NORMAL)
  and `'after'` (META auto-returns to NORMAL) live in the same dict as integer
  key codes, discriminated by type.

The redesign replaces this with a **named command table** — the keystone that
also delivers three things the current shape can't:

1. Emacs-style descriptive command names (defaulting to the function name).
2. A dynamic help screen derived from the table (can't drift out of sync).
3. A seam where an external keymap file (YAML) plugs in later — the keymap
   becomes `key → command-name`, which *is* the serializable form.

Named commands are also the most Forth-faithful structure: a dictionary of
named words is exactly what the port needs.

Out of scope for this round (the design leaves the seams, does not build them):
the YAML keymap file, a `--keymap` CLI overlay, and keyboard-macro
record/replay. See *Deferred* below.

## Design

### 1. Command & registry

```python
@dataclass(frozen=True)
class Command:
    name: str                       # 'move-forward-char'
    run: Callable[[], None]         # uniform zero-arg callable
    help: str = ''
```

The Controller builds a single registry `self.commands: dict[str, Command]` —
the "dictionary" of words. A helper registers a callable, defaulting the name
from the function's `__name__` (kebab-cased):

```python
def _register(self, fn: Callable[[], None], name: str | None = None, help: str = '') -> str:
    name = name or fn.__name__.replace('_', '-')
    self.commands[name] = Command(name, fn, help)
    return name
```

`ed.move_forward_char` auto-registers as `move-forward-char`. Explicit names are
supplied only for closures (`insert-tab`, `enter-meta`, `search-forward`) or
when a nicer name than the method is wanted. `help` is optional; the name alone
documents most commands.

**Two namespaces, principled split** (enabled by the facade, §4):

- **buffer commands** — `ed.*`: all cursor motion (char/word/line/page) and
  editing (insert/delete/cut/copy/paste/undo/redo/search/mark).
- **app & view commands** — `self.*` (save, quit, mode entry, help) and
  `dpy.recenter`.

No binding reaches into `layout.*`; line/page motion is exposed through `ed`.

### 2. Modes

Commands are the open, user-facing vocabulary → referenced by **string name**.
Modes are a small, closed, structural set → referenced by the existing
`KeyMode` enum (typo-safe, no forward-reference problem).

```python
@dataclass
class Mode:
    name: KeyMode
    bindings: dict[int, str]                 # key code -> command name (pure data, YAML-ready)
    default: Callable[[int], bool]           # unbound-key strategy; returns handled?
    transient: bool = False                  # prefix mode: pop after a single dispatch
```

`default` is the single, required per-mode strategy for a key with no explicit
binding — it subsumes what were three optional fields (`on_text`, `on_miss`,
`retry_in`). It returns **handled?**: `True` = key consumed; `False` = "not
mine — pop this mode and re-dispatch the key beneath it."

The three modes:

| Mode | `default(key)` | `transient` |
|------|----------------|-------------|
| `NORMAL`  | printable → `ed.insert(key)` → `True`; else beep → `True` (base; never declines) | `False` |
| `ISEARCH` | printable → `ed.isearch_insert(chr(key))` → `True`; else `ed.isearch_exit()` → `False` | `False` |
| `META`    | beep → `True` (all real keys are bound) | `True` |

So the old `'fallback'` becomes "`default` returns `False`" and the old
`'after'` becomes `transient=True`. Two knobs remain, but they are two genuinely
distinct concepts — **key resolution** (`default`) and **mode lifetime**
(`transient`) — each exercised by every mode, rather than three optionals each
firing in one mode.

### 3. Mode stack & dispatcher

The Controller holds two mode structures: `self.modes: dict[KeyMode, Mode]` is
the fixed registry of mode *definitions*; `self.stack: list[Mode]` is the
runtime stack, initialized to `[self.modes[KeyMode.NORMAL]]`. `NORMAL` is the
base; `ISEARCH` and `META` are pushed on top. The stack is only ever ~2 deep
here, but it makes "pop and retry" meaningful *without naming a target mode*
(which is what removes the last hardcoded `retry_in`/`after` target), and it is
the honest model for prefix and minor modes if any are added later. The push
helper resolves the enum: `self._push(m: KeyMode)` does
`self.stack.append(self.modes[m])`.

"Beep" throughout means the existing user-alert path — `self.dpy.show_message(
f'No action for ${key:02x} in {mode.name.name}', warn=True)` — not a new
mechanism.

```python
def dispatch(self, key: int) -> None:
    mode = self.stack[-1]
    name = mode.bindings.get(key)
    if name:
        self.commands[name].run()
    elif not mode.default(key):              # default declined -> pop and re-dispatch below
        self.stack.pop()
        return self.dispatch(key)
    if mode.transient and self.stack[-1] is mode:
        self.stack.pop()
```

Termination: a declining `default` returns `False` only from a pushed mode
(ISEARCH); `NORMAL`'s default never declines, so the recursion pops at most to
the base. Bounded by stack depth.

Mode changes are ordinary commands whose closures manipulate the stack via
Controller helpers `self._push(mode)` / `self._pop()`:

- `enter-meta`: `self._push(KeyMode.META)`
- `search-forward` (NORMAL C-S): `self._push(KeyMode.ISEARCH); ed.isearch_forward()`
- `search-backward` (NORMAL C-R): `self._push(KeyMode.ISEARCH); ed.isearch_backward()`
- `isearch-forward` / `isearch-backward` (ISEARCH C-S/C-R): `ed.isearch_forward` /
  `ed.isearch_backward` (no stack change — repeat in place)
- `isearch-cancel` (ISEARCH Esc): `ed.isearch_cancel(); self._pop()`

This deletes the `Action`/`Actionable` union, `actionlist`, and the list-action
machinery: a **compound command is simply a command whose closure calls other
commands** (e.g. `search-forward` above). No special compound type.

### 4. Facade — Editor as the buffer-command namespace

`Editor.__init__` gains six one-line delegations so line/page motion is
reachable through `ed`:

```python
self.move_start_line     = layout.move_start_line
self.move_end_line       = layout.move_end_line
self.move_forward_line   = layout.move_forward_line
self.move_backward_line  = layout.move_backward_line
self.move_forward_page   = layout.move_forward_page
self.move_backward_page  = layout.move_backward_page
```

Method **bodies stay in `Layout`** — `_vertical_move` keeps its ladder and
`goal_col` state there (delegation, not relocation; preserves the earlier
paint/command-separation work). `Editor` already holds a `layout` reference and
already calls `layout.move_*_line` inside `_clip_line`, so this is consistent
with existing structure. The perftest scenarios call `ed.*`/`layout.*` directly
and are unaffected.

### 5. Help screen (Python-only, derived)

Because names/help live in the registry and bindings are `key → name`, help is
pure formatting. A `describe-bindings` command (bound to `Esc ?`) walks each
mode's `bindings` and renders `keyname → command-name — help` lines.

One new View primitive: `Display.show_overlay(lines: list[str]) -> None` paints a
scroll of text over the buffer; the Controller enters a transient HELP mode that
any key pops (returning to a normal repaint). The whole help path is cleanly
separable — a 6502 port omits it — and it is the same seam where a future
`--keymap file.yaml` plugs in (load → validate against the registry → replace
`bindings`).

Key-code → display-name formatting (e.g. `9 → "C-I"`, `27 → "Esc"`,
`curses.KEY_LEFT → "Left"`) lives in a small `keyname(code) -> str` helper.

### 6. Startup validation

After building the registry and modes, assert every bound name resolves:

```python
for mode in self.modes.values():
    for key, name in mode.bindings.items():
        assert name in self.commands, f"{mode.name.name}: {keyname(key)} -> unknown command {name!r}"
```

This catches typos in the string-named bindings and is exactly the validator a
loaded YAML config reuses later.

## Behavior preservation

This is a behavior-preserving refactor of dispatch. Every current key must do
what it does today, including:

- printable self-insert in NORMAL; self-insert-into-search in ISEARCH;
- `C-I`→tab, `C-J`→newline, `KEY_ENTER`→newline (now named `insert-tab` /
  `insert-newline` commands, not bare-int self-inserts);
- ISEARCH: `C-S`/`C-R` repeat; `Esc` cancels (restores origin) and returns to
  NORMAL; backspace trims search; any other key exits search (leaving point)
  and is re-dispatched in NORMAL — e.g. an arrow key exits search *and* moves;
- META: one key after `Esc`, then auto-return to NORMAL; unknown META key beeps
  and still returns to NORMAL;
- the mark-clearing, save/quit, and autosave behavior around these keys.

## Testing

- **Characterization first.** The existing `tests/test_editor.py` isearch and
  dispatch tests drive `Controller.dispatch` and must stay green unchanged.
- **New unit tests:**
  - registry completeness — the startup validation passes; every mode binding
    resolves to a registered command;
  - each mechanic — NORMAL self-insert; ISEARCH printable extends search;
    ISEARCH unbound key (arrow) exits search AND performs the motion
    (the pop-and-retry path); META one-shot returns to NORMAL after one key;
    META unknown key beeps and returns;
  - the mode-entry composites (`search-forward` pushes ISEARCH and searches);
  - help — `describe-bindings` renders a line for every command in every mode
    without error.
- Golden render tests remain byte-identical (dispatch changes don't touch the
  render path).

## Deferred (seams left, not built)

- **External keymap file (YAML) + `--keymap` overlay.** `bindings` is already
  `dict[int, str]`; a loader parses `{keyname: command-name}`, maps keynames to
  codes, and runs the §6 validator before replacing a mode's `bindings`. The
  registry is the fixed vocabulary it validates against.
- **Keyboard macros (record/replay).** A compound is already just a command
  calling others; a config value of `[name, name, ...]` would wrap into one
  compound command at load. Recording is a separate feature, not needed now.

## Resolved design decisions

- Command references are **strings** (open vocabulary; config/help/Forth);
  mode references are the **`KeyMode` enum** (small closed set; typo-safe).
- The unbound-key strategy is a single required `default(key) -> bool`
  (**handled?**), not three optional fields; `Disp` enum rejected — a two-value
  result is a bool.
- Mode lifetime is a **stack** with a `transient` pop-after-one flag, not named
  retry/after targets.
- **No compound-action type**; compounds are closures over other commands.
- Facade **delegates**, does not relocate, Layout's line/page methods.
