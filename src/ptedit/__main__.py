import curses
from curses import wrapper
import argparse

from .controller import Controller
from .screen import Screen, CursesScreen


def main():
    parser = argparse.ArgumentParser(
        prog='ptedit',
        description='Prototype of minimal piece-table-based ascii editor',
    )
    parser.add_argument('filename')
    parser.add_argument('-P', '--perftest', nargs='?', const='insert', default=None,
                        help='Run perftest scenario (insert|up_from_end|pgup_from_end|pgdn_from_top)')
    args = parser.parse_args()

    if args.perftest is not None:
        # Bypass curses entirely — perftest only exercises Display.paint() and Layout,
        # so a mock Screen (no TTY required) gives comparable numbers without curses I/O noise.
        scr = Screen(height=24, width=80)
        ctrl = Controller(args.filename, scr)
        result = ctrl.perftest(args.perftest)
        print(result)
    else:
        result = wrapper(main_loop, args)
        if result:
            print(result)


def main_loop(stdscr: curses.window, args: argparse.Namespace):
    scr = CursesScreen(stdscr)
    ctrl = Controller(args.filename, scr, getch=stdscr.getch)
    ctrl.interactive()
    return None

if __name__ == "__main__":
    main()
