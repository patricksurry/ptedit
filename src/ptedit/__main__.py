import curses
from curses import wrapper
import sys
import os

from .piecetable import PieceTable
from .controller import Controller
from .keymap import control_keys, meta_keys


if len(sys.argv) != 2:
    sys.exit("Usage: python3 -m src/ptedit fname")


def main_loop(stdscr):

    fname = sys.argv[1]
    if not os.path.exists(fname):
        open(fname, 'w').close()

    data = open(fname).read()
    doc = PieceTable(data)

    stdscr.scrollok(False)
    # the actual cursor shape is determined by the terminal, e.g. for OS X terminal
    # use Terminal > Settings > Text > Cursor to pick vert or horiz bar vs block etc
    curses.curs_set(2)          # 0 is invisible, 1 is normal, 2 is high-viz (e.g. block)
    height, width = stdscr.getmaxyx()
    controller = Controller(doc, height, width, fname=fname, control_keys=control_keys, meta_keys=meta_keys)

    while controller.doc:
        controller.paint(stdscr)
        key = stdscr.getch()
        controller.key_handler(key)

wrapper(main_loop)
