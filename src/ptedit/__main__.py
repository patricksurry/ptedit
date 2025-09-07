# python3 -m src/ptedit [-P] filename

import curses
from curses import wrapper
import argparse

from .controller import Controller


def main():
    parser = argparse.ArgumentParser(
        prog='ptedit',
        description='Prototype of minimal piece-table-based ascii editor',
    )
    parser.add_argument('filename')
    parser.add_argument('-P', '--perftest', action='store_true', help="Performance test")
    args = parser.parse_args()

    result = wrapper(main_loop, args)
    if result:
        print(result)


def main_loop(stdscr: curses.window, args: argparse.Namespace):
    ctrl = Controller(args.filename, stdscr)

    if args.perftest:
        return ctrl.perftest()
    else:
        ctrl.interactive()
        return None

if __name__ == "__main__":
    main()

