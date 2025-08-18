# python3 -m src/ptedit [-P] filename

import curses
from curses import wrapper
from time import time
import os
import argparse

from .piecetable import PieceTable
from .controller import Controller
from .keymap import control_keys, meta_keys


def main_loop(stdscr, args):

    if not os.path.exists(args.filename):
        open(args.filename, 'w').close()

    data = open(args.filename).read()
    doc = PieceTable(data)

    stdscr.scrollok(False)
    # the actual cursor shape is determined by the terminal, e.g. for OS X terminal
    # use Terminal > Settings > Text > Cursor to pick vert or horiz bar vs block etc
    curses.curs_set(2)          # 0 is invisible, 1 is normal, 2 is high-viz (e.g. block)
    height, width = stdscr.getmaxyx()
    controller = Controller(doc, height, width, fname=args.filename, control_keys=control_keys, meta_keys=meta_keys)

    if args.perftest:
        doc.move_point(doc.length//2)

    global frames
    while controller.doc:
        controller.paint(stdscr)
        frames += 1
        if args.perftest:
            if time() - start > 1:
                break
        else:
            key = stdscr.getch()
            controller.key_handler(key)

parser = argparse.ArgumentParser(
    prog='ptedit',
    description='Prototype of minimal piece-table-based ascii editor',
)
parser.add_argument('filename')
parser.add_argument('-P', '--perftest', action='store_true', help="Performance test")
args = parser.parse_args()

start = time()
frames = 0

wrapper(main_loop, args)

print(f"Terminated after {time()-start:0.1}s, {frames} repaints")
