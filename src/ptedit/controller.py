import curses
import os
from time import time
from enum import IntEnum
from typing import Callable, Literal, cast

from .piecetable import Document
from .editor import Editor
from .renderer import Renderer, CursesScreen


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

        doc = Document(open(fname).read())

        self.save = lambda: doc.save(fname)

        self.rdr = Renderer(doc, CursesScreen(stdscr), fname)
        self.ed = Editor(doc, self.rdr)
        self.getch = stdscr.getch
        self.active = True

        # printable ascii keys insert themselves
        printable = {k: k for k in range(32,127)}
        ed = self.ed
        self.keymap: list[dict[ActionKey, Actionable]] = [
            # KeyMode.NORMAL
            {
                curses.KEY_LEFT: ed.move_backward_char,
                curses.KEY_RIGHT: ed.move_forward_char,
                curses.KEY_UP: ed.move_backward_line,
                curses.KEY_DOWN: ed.move_forward_line,
                curses.KEY_ENTER: ord('\n'),  # NL
                curses.KEY_BACKSPACE: ed.delete_backward_char,  # bksp ^H
                127: ed.delete_backward_char,
                ctrl('A'): ed.move_start_line,
                ctrl('B'): ed.move_backward_word,
                ctrl('F'): ed.move_forward_word,
                ctrl('E'): ed.move_end_line,
                ctrl('D'): ed.delete_forward_char,
                ctrl('I'): ord('\t'),           # tab
                ctrl('J'): ord('\n'),           # newline
                ctrl('L'): self.rdr.clear_top,  # redraw screen
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
                ord('a'): ed.move_backward_page,
                ord('b'): ed.move_backward_para,
                ord('f'): ed.move_forward_para,
                ord('e'): ed.move_forward_page,
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

    def interactive(self):
        while self.active:
            self.rdr.paint(self.ed.mark)
            key = self.getch()
            self.dispatch(key)

    def quit(self):
        self.active = False

    def perftest(self, max_time: float=1.0) -> str:
        self.ed.move_end()
        frames = 0
        start = time()

        while time() - start < max_time:
            self.rdr.paint(self.ed.mark)
            frames += 1
            self.ed.move_backward_char()
            self.ed.move_backward_line()

        return f"Repainted {frames} frames in {time()-start:0.1}s"

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
            self.rdr.show_status(
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
