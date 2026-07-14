from __future__ import annotations
import curses
import os
from time import time
from enum import IntEnum
from dataclasses import dataclass
from typing import Callable

import logging


from .document import Document
from .editor import Editor
from .display import Display, Cell
from .screen import Screen


logging.basicConfig(level=logging.INFO, filename='ptedit.log', filemode='w')


class KeyMode(IntEnum):
    NORMAL = 0
    ISEARCH = 1
    META = 2
    HELP = 3


# note curses won't see all control keys since zsh is intercepting some
# for example, to use ctrl-S/ctrl-Q (normally xon/xoff) disable flow control
# on OS X add `stty -ixon` to your .zshrc file
# to allow ctrl-O on OS X add `stty discard undef`

# These are normal ascii key-presses that trigger editing commands
# The normal printable characters (ascii 32-126 inclusive) insert themselves
# Any ascii value not otherwise mentioned will show as an error
# Normally these are generated as control keys, but you can also
# map 8-bit ascii values (>127) if your keyboard can generate them

def ctrl(c: str) -> int:
    """
    Note that control-keys are case-insenstive, i.e. shift doesn't matter.
    In fact only the lower five bits matter, so C-@ and C-space are normally equivalent.
    """
    return ord(c[0]) & 0b11111


# Codes with a nicer label than the raw control-chord / character.
_KEYNAMES: dict[int, str] = {
    27: 'Esc',
    32: 'Space',
    127: 'Del',
    curses.KEY_LEFT: 'Left',
    curses.KEY_RIGHT: 'Right',
    curses.KEY_UP: 'Up',
    curses.KEY_DOWN: 'Down',
    curses.KEY_ENTER: 'Enter',
    curses.KEY_BACKSPACE: 'Bksp',
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


@dataclass
class Mode:
    # A mode's identity is the KeyMode it is stored under in Controller.modes,
    # so it isn't repeated here.
    bindings: dict[int, str]                  # key code -> command name
    on_unbound: Callable[[int], bool]         # unbound key: returns handled?
    transient: bool = False                   # prefix mode: pop after one dispatch

    def chord_for(self, command: str) -> int | None:
        """The key bound to `command` in this mode, or None."""
        for key, name in self.bindings.items():
            if name == command:
                return key
        return None


class Controller:
    def __init__(self, fname: str, scr: Screen, getch: Callable[[], int] | None = None) -> None:
        # create missing file
        if not os.path.exists(fname):
            open(fname, 'w').close()

        self.fname: str = fname
        self.change_count: int = 0

        # use iso-8859-1 so that str <-> bytes is 1:1
        self.doc = Document(open(fname, encoding='iso-8859-1').read())
        self.dpy = Display(self.doc, scr)
        self.ed = Editor(
            self.doc,
            self.dpy.layout,
            notify=self.dpy.show_message,
        )
        self.getch = getch
        self.active = True

        ed = self.ed
        dpy = self.dpy

        # The command registry: a name -> zero-arg callable "dictionary" of
        # words. Bare callables are auto-named from __name__ (kebab-cased);
        # (callable, name) pairs name a closure explicitly.
        self.commands: dict[str, Callable[[], None]] = {}
        self.register_commands([
            # buffer commands
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
            # app / view commands (composites auto-name: enter_meta -> enter-meta)
            dpy.recenter, self.save, self.quit,
            self.enter_meta, self.search_forward, self.search_backward,
            self.isearch_cancel, self.describe_bindings, self.help_page_back,
            (lambda: ed.insert(ord('\t')), 'insert-tab'),
            (lambda: ed.insert(ord('\n')), 'insert-newline'),
        ])

        self.modes: dict[KeyMode, Mode] = {
            KeyMode.NORMAL: Mode({
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
            KeyMode.ISEARCH: Mode({
                ctrl('S'): 'isearch-forward',
                ctrl('R'): 'isearch-backward',
                ctrl('['): 'isearch-cancel',
                127: 'isearch-delete',
            }, on_unbound=self._isearch_unbound),
            KeyMode.META: Mode({
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
                ord('?'): 'describe-bindings',
            }, on_unbound=self._meta_unbound, transient=True),
            # HELP pages the binding list: Left/Up/Bksp/Del page back, any other
            # key pages forward and dismisses past the last page.
            KeyMode.HELP: Mode({
                curses.KEY_LEFT: 'help-page-back',
                curses.KEY_UP: 'help-page-back',
                curses.KEY_BACKSPACE: 'help-page-back',
                127: 'help-page-back',
            }, on_unbound=self._help_unbound),
        }
        # The runtime mode stack holds KeyMode values keying into self.modes;
        # NORMAL is the base, prefix/help modes push on top.
        self.mode_stack: list[KeyMode] = [KeyMode.NORMAL]
        self.help_page: int = 0

        self._validate_bindings()

    def status_message(self, cursor: Cell) -> str:
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
                f"pos {len(pt_data)}/{len(doc_data)}",
                f"lns {pt_nl}/{doc_nl}",
                f"pcs {pt_pieces}/{all_pieces}",
                f"eds {pt_edits}/{all_edits}",
            ])

        return " " + status

    def interactive(self) -> None:
        while self.active:
            if self.mode_stack[-1] is KeyMode.HELP:
                self.dpy.show_overlay(self._help_lines())
                cursor = Cell(0, 0)
                pages = self._help_pages()
                if pages == 1:
                    status = ' HELP - any key to dismiss'
                else:
                    status = (f' HELP page {self.help_page + 1}/{pages}'
                              ' - any key forward, Left/Bksp back')
            else:
                cursor = self.dpy.paint(self.ed.mark)
                status = self.status_message(cursor)
            self.dpy.scr.move(self.dpy.rows, 0)
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

    def quit(self) -> None:
        self.autosave(0)
        self.active = False

    def save(self, suffix: str = '') -> None:
        open(self.fname + suffix, 'w', encoding='iso-8859-1').write(self.doc.get_data())
        self.doc.dirty = False

    def autosave(self, interval: int = 10) -> None:
        if interval:
            self.change_count = (self.change_count + 1)%interval
        else:
            self.change_count = 0
        if self.change_count == 0 and self.doc.dirty:
            self.save('~')

    def perftest(self, scenario: str = 'insert', max_time: float = 1.0) -> str:
        runners = {
            'insert':        self._perf_insert_loop,
            'up_from_end':   self._perf_up_from_end,
            'pgup_from_end': self._perf_pgup_from_end,
            'pgdn_from_top': self._perf_pgdn_from_top,
        }
        if scenario not in runners:
            return f"unknown scenario: {scenario}; choices: {list(runners)}"
        return runners[scenario](max_time)

    def _run(self, max_time: float, step: Callable[[], None]) -> str:
        frames = 0
        start = time()
        while time() - start < max_time:
            self.dpy.paint(self.ed.mark)
            frames += 1
            step()
        elapsed = time() - start
        return f"{frames} frames in {elapsed:0.2f}s = {frames/elapsed:.0f} fps"

    def _perf_insert_loop(self, max_time: float) -> str:
        self.ed.move_end()
        def step() -> None:
            self.ed.insert(ord('a'))
            self.ed.move_backward_char()
            self.dpy.layout.move_backward_line()
        return self._run(max_time, step)

    def _perf_up_from_end(self, max_time: float) -> str:
        self.ed.move_end()
        def step() -> None:
            if self.doc.at_start():
                self.ed.move_end()
            self.dpy.layout.move_backward_line()
        return self._run(max_time, step)

    def _perf_pgup_from_end(self, max_time: float) -> str:
        self.ed.move_end()
        def step() -> None:
            if self.doc.at_start():
                self.ed.move_end()
            self.dpy.layout.move_backward_page()
        return self._run(max_time, step)

    def _perf_pgdn_from_top(self, max_time: float) -> str:
        self.ed.move_start()
        def step() -> None:
            if self.doc.at_end():
                self.ed.move_start()
            self.dpy.layout.move_forward_page()
        return self._run(max_time, step)

    def register_commands(self, items: list) -> None:
        """Register commands from a list of bare callables (auto-named from
        __name__, kebab-cased) or (callable, name) pairs."""
        for item in items:
            fn, name = item if isinstance(item, tuple) else (item, None)
            name = name or fn.__name__.replace('_', '-')
            assert name not in self.commands, name    # duplicate would silently shadow
            self.commands[name] = fn

    def _validate_bindings(self) -> None:
        """Every bound command name must resolve (also the future YAML-config
        validator)."""
        bound = {name for mode in self.modes.values() for name in mode.bindings.values()}
        missing = bound - set(self.commands)
        assert not missing, f'bindings reference unknown commands: {sorted(missing)}'

    def _push(self, m: KeyMode) -> None:
        self.mode_stack.append(m)

    def _pop(self) -> None:
        assert len(self.mode_stack) > 1, "cannot pop the base mode"
        self.mode_stack.pop()

    def enter_meta(self) -> None:
        self._push(KeyMode.META)

    def search_forward(self) -> None:
        self._push(KeyMode.ISEARCH)
        self.ed.isearch_forward()

    def search_backward(self) -> None:
        self._push(KeyMode.ISEARCH)
        self.ed.isearch_backward()

    def isearch_cancel(self) -> None:
        self.ed.isearch_cancel()
        self._pop()

    def describe_bindings(self) -> None:
        if self.modes[self.mode_stack[-1]].transient:   # leave the META prefix we arrived through
            self._pop()
        self.help_page = 0
        self._push(KeyMode.HELP)

    def help_page_back(self) -> None:
        self.help_page = max(0, self.help_page - 1)

    def _help_unbound(self, key: int) -> bool:
        # Any non-back key pages forward; past the last page it dismisses.
        if self.help_page + 1 < self._help_pages():
            self.help_page += 1
        else:
            self._pop()
        return True

    # --- Help: a paged grid of every key chord and the command it runs. ---
    # Cell width is 26 at 80 cols (6 for the chord, 20 for the command);
    # ncols scales with terminal width, and content spills onto extra pages
    # rather than being truncated or dropped.

    def _help_entries(self) -> list[tuple[str, str]]:
        """Every (chord, command) binding across the editing modes, sorted by
        command name. META keys carry their `Esc ` prefix so the chord is
        unambiguous (a bare `v` would read like self-insert)."""
        entries: list[tuple[str, str]] = []
        for km in (KeyMode.NORMAL, KeyMode.META, KeyMode.ISEARCH):
            for key, name in self.modes[km].bindings.items():
                entries.append((self._binding_chord(km, key), name))
        entries.sort(key=lambda e: e[1])
        return entries

    def _binding_chord(self, km: KeyMode, key: int) -> str:
        """Full chord for `key` in mode `km`, prefixing the key that enters a
        non-base prefix mode (e.g. META's `v` -> `Esc v`)."""
        if km is KeyMode.NORMAL:
            return keyname(key)
        enter = self.modes[KeyMode.NORMAL].chord_for(f'enter-{km.name.lower()}')
        prefix = f'{keyname(enter)} ' if enter is not None else ''
        return f'{prefix}{keyname(key)}'

    def _help_grid(self) -> tuple[int, int, int]:
        """(ncols, colw, keyw) for the current terminal. The cell is sized to
        the actual bindings — `keyw` for the widest chord, the rest for the
        widest command — so nothing is truncated or bled into the next column
        (the lone `Esc Esc` chord is 7 wide, so a cell is 28, not the nominal
        26). Columns pack to the terminal width with 1-char gutters; a cell
        wider than the whole terminal (a very narrow screen) is clipped."""
        entries = self._help_entries()
        keyw = max((len(chord) for chord, _ in entries), default=0)
        cmdw = max((len(cmd) for _, cmd in entries), default=0)
        cellw = keyw + 1 + cmdw
        ncols = max(1, (self.dpy.cols + 1) // (cellw + 1))
        colw = cellw if ncols * (cellw + 1) - 1 <= self.dpy.cols else self.dpy.cols
        return ncols, colw, keyw

    def _help_pages(self) -> int:
        ncols, _, _ = self._help_grid()
        return max(1, -(-len(self._help_entries()) // (ncols * self.dpy.rows)))

    def _help_lines(self) -> list[str]:
        """The current help page as screen rows: a column-major grid of
        `chord command` cells, each padded to the column width."""
        ncols, colw, keyw = self._help_grid()
        rows = self.dpy.rows
        entries = self._help_entries()
        page = max(0, min(self.help_page, self._help_pages() - 1))
        chunk = entries[page * ncols * rows:(page + 1) * ncols * rows]
        cells = [f'{chord:<{keyw}} {cmd}'[:colw] for chord, cmd in chunk]
        lines = []
        for r in range(rows):
            row = [cells[c * rows + r].ljust(colw)
                   for c in range(ncols) if c * rows + r < len(cells)]
            lines.append(' '.join(row).rstrip())
        return lines

    def _chord_for(self, command: str) -> str | None:
        """Human chord that invokes `command`, e.g. 'Esc ?', or None if unbound.
        Prefers a direct NORMAL binding, else the first prefix mode that has it."""
        for km in self.modes:
            key = self.modes[km].chord_for(command)
            if key is not None:
                return self._binding_chord(km, key)
        return None

    def _beep(self, key: int) -> None:
        hint = self._chord_for('describe-bindings')
        suffix = f' - {hint} for help' if hint else ''
        self.dpy.show_message(
            f'No action for {keyname(key)} in {self.mode_stack[-1].name}{suffix}',
            True)

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
        km = self.mode_stack[-1]
        mode = self.modes[km]
        name = mode.bindings.get(key)
        if name:
            self.commands[name]()
        elif not mode.on_unbound(key):        # declined -> pop and re-dispatch below
            self.mode_stack.pop()
            return self.dispatch(key)
        if mode.transient and self.mode_stack[-1] == km:
            self.mode_stack.pop()
