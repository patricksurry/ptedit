import curses
from dataclasses import dataclass


@dataclass
class Screen:
    """Abstract screen interface, used as mock for testing"""
    height: int
    width: int

    def clear(self):
        """clear the screen and move cursor to top-left"""
        pass

    def refresh(self):
        """refresh display"""
        pass

    def alert(self):
        """optionally alert the user, e.g. flash, bell"""
        pass

    def move(self, row: int, col: int):
        pass

    def put(self, ch: int, highlight: bool=False):
        """put character and increment position"""
        pass

    def puts(self, s: str, highlight: bool=False):
        for c in s:
            self.put(ord(c), highlight)


class CursesScreen(Screen):
    def __init__(self, win: curses.window):
        self.win = win
        self.win.scrollok(False)
        # the actual cursor shape is determined by the terminal, e.g. for OS X terminal
        # use Terminal > Settings > Text > Cursor to pick vert or horiz bar vs block etc
        curses.curs_set(2)          # 0 is invisible, 1 is normal, 2 is high-viz (e.g. block)
        self.height, self.width = self.win.getmaxyx()
        assert self.height > 1 and self.width > 0

    def clear(self):
        self.win.clear()

    def refresh(self):
        self.win.refresh()

    def move(self, row: int, col: int):
        self.win.move(row, col)

    def put(self, ch: int, highlight: bool=False):
        try:
            # ignore the error if we advance past the end of the screen
            self.win.addch(ch, curses.A_REVERSE if highlight else curses.A_NORMAL)
        except curses.error:
            pass



