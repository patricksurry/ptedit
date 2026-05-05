import curses
import os
from time import time
from enum import IntEnum
from typing import Callable, Literal, cast

import logging


from .document import Document, Location
from .editor import Editor
from .display import Display
from .screen import CursesScreen


logging.basicConfig(level=logging.INFO, filename='ptedit.log', filemode='w')


class KeyMode(IntEnum):
    NORMAL = 0
    ISEARCH = 1
    META = 2


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


ActionFn = Callable[[], None]
Action = KeyMode | int | ActionFn
Actionable = None | Action | list[Action]
ActionKey = int | Literal["fallback"] | Literal["after"]


def actionlist(actionable: Actionable) -> list[Action]:
    if isinstance(actionable, list):
        return cast(list[Action], actionable)
    elif actionable is not None:
        return [actionable]
    else:
        return []


class Controller:
    def __init__(self, fname: str, stdscr: curses.window):
        self.mode = KeyMode.NORMAL

        # create missing file
        if not os.path.exists(fname):
            open(fname, 'w').close()

        self.fname = fname
        self.change_count = 0

        # use iso-8859-1 so that str <-> bytes is 1:1
        self.doc = Document(open(fname, encoding='iso-8859-1').read())
        self.doc.watch(self.change_handler)
        self.dpy = Display(self.doc, CursesScreen(stdscr))
        self.ed = Editor(
            self.doc,
            self.dpy.layout,
            notify=self.dpy.show_message,
        )
        self.getch = stdscr.getch
        self.active = True

        # printable ascii keys insert themselves
        printable = {k: k for k in range(32,127)}
        ed = self.ed
        dpy = self.dpy
        layout = self.dpy.layout
        self.keymap: list[dict[ActionKey, Actionable]] = [
            # KeyMode.NORMAL
            {
                curses.KEY_LEFT: ed.move_backward_char,
                curses.KEY_RIGHT: ed.move_forward_char,
                curses.KEY_UP: layout.move_backward_line,
                curses.KEY_DOWN: layout.move_forward_line,
                curses.KEY_ENTER: ord('\n'),  # NL
                curses.KEY_BACKSPACE: ed.delete_backward_char,  # bksp ^H
                127: ed.delete_backward_char,
                ctrl('A'): layout.move_start_line,
                ctrl('B'): ed.move_backward_word,
                ctrl('F'): ed.move_forward_word,
                ctrl('E'): layout.move_end_line,
                ctrl('D'): ed.delete_forward_char,
                ctrl('I'): ord('\t'),           # tab
                ctrl('J'): ord('\n'),           # newline
                ctrl('L'): dpy.recenter,  # redraw screen
                ctrl('Y'): ed.redo,
                ctrl('Z'): ed.undo,
                ctrl('['): KeyMode.META,      # escape
                ctrl('_'): ed.squash,
                ctrl('S'): [KeyMode.ISEARCH, ed.isearch_forward],
                ctrl('R'): [KeyMode.ISEARCH, ed.isearch_backward],
                ctrl('O'): ed.toggle_overwrite,
                **printable
            },
            # KeyMode.ISEARCH
            {
                # A few keys stay in ISEARCH mode and otherwise
                # we fall through and retry in NORMAL mode
                'fallback': [ed.isearch_exit, KeyMode.NORMAL],

                ctrl('S'): ed.isearch_forward,
                ctrl('R'): ed.isearch_backward,
                ctrl('['): [ed.isearch_cancel, KeyMode.NORMAL],
                127: ed.delete_backward_char,
                **printable,
            },
            # KeyMode.META
            # These are keys entered after an initial Escape (C-[) is entered
            # Any valid ascii value can be used, e.g. a, A, C-A are all distinct options
            {
                'after': KeyMode.NORMAL,

                ctrl('['): ed.clear_mark,
                ord('a'): layout.move_backward_page,
                ord('b'): ed.move_backward_para,
                ord('f'): ed.move_forward_para,
                ord('e'): layout.move_forward_page,
                ord('A'): ed.move_start,
                ord('E'): ed.move_end,
                ord('m'): ed.set_mark,
                ord('s'): self.save,
                ord('q'): self.quit,
                ord('c'): ed.copy,
                ord('k'): ed.cut_line,
                ord('K'): ed.copy_line,
                ord('x'): ed.cut,
                ord('v'): ed.paste,
                ord('y'): ed.redo,
                ord('z'): ed.undo,
            }
        ]

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

    def interactive(self):
        while self.active:
            cursor = self.dpy.paint(self.ed.mark)
            self.dpy.scr.move(self.dpy.rows, 0)
            status = self.status_message(cursor)
            status = (status[:self.dpy.cols] if len(status) >= self.dpy.cols
                      else status + ' ' * (self.dpy.cols - len(status)))
            self.dpy.scr.puts(status, highlight=True)
            self.dpy.scr.move(*cursor)
            self.dpy.scr.refresh()
            try:
                key = self.getch()
                logging.info(f'key ${key:02x}')
                self.dispatch(key)
            except KeyboardInterrupt:
                self.quit()

    def quit(self):
        self.autosave(0)
        self.active = False

    def save(self, suffix: str=''):
        open(self.fname + suffix, 'w', encoding='iso-8859-1').write(self.doc.get_data())
        self.doc.dirty = False

    def autosave(self, interval: int=10):
        if interval:
            self.change_count = (self.change_count + 1)%interval
        else:
            self.change_count = 0
        if self.change_count == 0 and self.doc.dirty:
            self.save('~')

    def change_handler(self, start: Location, end: Location):
        self.autosave()

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

    def _run(self, max_time: float, step) -> str:
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
        def step():
            self.ed.insert(ord('a'))
            self.ed.move_backward_char()
            self.dpy.layout.move_backward_line()
        return self._run(max_time, step)

    def _perf_up_from_end(self, max_time: float) -> str:
        self.ed.move_end()
        def step():
            if self.doc.at_start():
                self.ed.move_end()
            self.dpy.layout.move_backward_line()
        return self._run(max_time, step)

    def _perf_pgup_from_end(self, max_time: float) -> str:
        self.ed.move_end()
        def step():
            if self.doc.at_start():
                self.ed.move_end()
            self.dpy.layout.move_backward_page()
        return self._run(max_time, step)

    def _perf_pgdn_from_top(self, max_time: float) -> str:
        self.ed.move_start()
        def step():
            if self.doc.at_end():
                self.ed.move_start()
            self.dpy.layout.move_forward_page()
        return self._run(max_time, step)

    def dispatch(self, key: int):
        """Handle an ascii keypress"""

        actions: list[Action] = []
        while True:
            keymap = self.keymap[self.mode]
            actions += actionlist(keymap.get(key))
            if actions or 'fallback' not in keymap:
                break
            self._act(actionlist(keymap['fallback']))

        if not actions:
            self.dpy.show_message(
                f'No action for key ${key:02x} in {self.mode.name} mode',
                True
            )

        actions += actionlist(keymap.get('after'))

        self._act(actions)

    def _act(self, actions: list[Action]):
        for action in actions:
            if callable(action):
                action()
            elif isinstance(action, KeyMode):
                self.mode = action
            else:
                self.ed.insert(action)
