import curses
from curses import wrapper, window
from os import path

from .piecetable import PieceTable, Location


#TODO maintain a 'place' mark for output, so can scan chars
# to count row/col and find where place=point

class Display:
    def __init__(self, doc: PieceTable, tab=8):
        self.doc = doc
        self.tab = tab
        self.breaks = [0]

    def wrap_line(self, width: int, start=False):
        """find soft break points for a line starting from point"""
        pt = self.doc.get_point()
        if start:
            self.breaks = [0]
        offset = self.breaks[-1]
        safe_break = 0
        col = 0
        while True:
            c = self.doc.next_char()
            offset += 1
            if c in ' -\t\n':
                safe_break = offset
            col += 1 if c != '\t' else (self.tab - (col % self.tab))
            if col >= width or c == '\n':
                if not safe_break:
                    safe_break = offset
                self.breaks.append(safe_break)
                if c == '\n':
                    break
                col = offset - safe_break
                safe_break = 0
        # reset the point
        self.doc.set_point(pt)

    def refresh(self, scr: window):
        height, width = scr.getmaxyx()

        pt = self.doc.get_point()
        self.doc.set_point(self.mark_frame(self.doc.get_start()))
        scr.clear()
        y = 0
        cursor = None
        while y < height:
            self.wrap_line(width, True)
            prev = self.breaks.pop(0)
            while self.breaks:
                try:
                    scr.move(y, 0)
                except:
                    print(f"move failed for {y}")
                brk = self.breaks.pop(0)
                n = brk - prev
                prev = brk
                for col in range(n):
                    if self.doc.get_point() == pt:
                        cursor = scr.getyx()
                    ch = ord(self.doc.next_char())
                    if 32 <= ch < 127:
                        if col < width-1:
                            scr.addch(ch)   # TODO tab, nl etc
                        else:
                            scr.insch(ch)   # TODO tab, nl etc
                y += 1
                if y == height:
                    break

        if cursor:
            scr.move(*cursor)
        self.doc.set_point(pt)
        scr.refresh()

    def mark_frame(self, preferred: Location, lines=8):
        pt = self.doc.get_point()
        while lines >= 0:
            self.doc.find_char_backward('\n')
            lines -= 1
        #TODO add a helper for is_start()
        if self.doc.get_point() != self.doc.get_start():
            self.doc.move_point(1)
        loc = self.doc.get_point()
        self.doc.set_point(pt)
        if self.doc.within_range(preferred, loc, pt):
            loc = preferred
        return loc


def main_loop(stdscr):

    stdscr.scrollok(False)
    curses.curs_set(2)

    display = Display(doc)

    while True:
        display.refresh()
        key = stdscr.getch()
        match key:
            case curses.KEY_LEFT:
                doc.move_point(-1)
            case curses.KEY_RIGHT:
                doc.move_point(1)
            case curses.KEY_UP:
                doc.move_point(-40)
            case curses.KEY_DOWN:
                doc.move_point(40)
            case curses.KEY_BACKSPACE | 127:
                doc.delete(-1)
            case _:
                if 32 <= key < 127:
                    doc.insert(chr(key))

if __name__ == "__main__":
    alice = open(path.join(path.dirname(__file__), '../../tests/alice1flow.asc')).read()
    doc = PieceTable(alice)
    doc.find_char_forward('\n')
    print(doc.get_point())

    wrapper(main_loop)
