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


@dataclass
class Mode:
    name: KeyMode
    bindings: dict[int, str]                  # key code -> command name
    on_unbound: Callable[[int], bool]         # unbound key: returns handled?
    transient: bool = False                   # prefix mode: pop after one dispatch


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
        self._register(self.describe_bindings, 'describe-bindings')

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
                ord('?'): 'describe-bindings',
            }, on_unbound=self._meta_unbound, transient=True),
            KeyMode.HELP: Mode(KeyMode.HELP, {}, on_unbound=self._help_unbound),
        }
        self.stack: list[Mode] = [self.modes[KeyMode.NORMAL]]

        # startup validation: every bound name resolves (also the future
        # YAML-config validator).
        for mode in self.modes.values():
            for key, name in mode.bindings.items():
                assert name in self.commands, \
                    f'{mode.name.name}: {keyname(key)} -> unknown command {name!r}'

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

    def _beep(self, key: int) -> None:
        hint = self._chord_for('describe-bindings')
        suffix = f' — {hint} for help' if hint else ''
        self.dpy.show_message(
            f'No action for {keyname(key)} in {self.stack[-1].name.name}{suffix}',
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
        mode = self.stack[-1]
        name = mode.bindings.get(key)
        if name:
            self.commands[name]()
        elif not mode.on_unbound(key):        # declined -> pop and re-dispatch below
            self.stack.pop()
            return self.dispatch(key)
        if mode.transient and self.stack[-1] is mode:
            self.stack.pop()
