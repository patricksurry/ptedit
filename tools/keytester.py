import curses
from curses import wrapper, window


def main_loop(stdscr: window):
    stdscr.scrollok(False)
    curses.curs_set(2)

    while True:
        key = stdscr.getch()
        msg = f"Ascii key pressed: {key}"
        if 0 <= key < 32:
            msg += f" (C-{chr(key+64)})"
        stdscr.addstr(5, 0, msg + " " * 20)
        stdscr.refresh()


if __name__ == "__main__":
    wrapper(main_loop)
