# python3 -m src/ptedit [-P] filename

import curses
from curses import wrapper
from time import time
import os
import argparse

from .piecetable import Document
from .editor import Editor
from .renderer import Renderer, CursesScreen
from .controller import Controller


#TODO open/file/dirty should be in doc
#TODO mutator should flag doc listeners
#TODO editor could trigger
def main_loop(stdscr, args):
    # create missing file
    if not os.path.exists(args.filename):
        open(args.filename, 'w').close()

    doc = Document(fname=args.filename)
    rdr = Renderer(doc, CursesScreen(stdscr))
    ed = Editor(doc, rdr)
    ctrl = Controller(ed, rdr.show_error)

    if args.perftest:
        doc.set_point(doc.get_end())

    global frames
    while ed.doc:       #TODO hack
        rdr.paint(ed.mark)
        frames += 1
        if args.perftest:
            ed.move_backward_char()
            ed.move_backward_line()
            if time() - start > 1:
                break
        else:
            key = stdscr.getch()
            ctrl.dispatch(key)

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
