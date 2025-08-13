import curses
from curses import wrapper, window
from os import path

from .piecetable import PieceTable, Location


#TODO maintain a 'place' mark for output, so can scan chars
# to count row/col and find where place=point

class Display:
    def __init__(self, doc: PieceTable, height: int, width: int, tab=8):
        self.doc = doc
        self.tab = tab
        self.height = height
        self.width = width

    def next_wrap(self):
        """
        Advance point to the next soft-break location,
        i.e. just past a newline/whitespace/hyphen or end of doc.
        """
        safe: Location | None = None
        col = 0
        while True:
            c = self.doc.next_char()
            if not c or c in ' -\t\n':
                safe = self.doc.get_point()
            col += 1 if c != '\t' else (self.tab - (col % self.tab))
            # time to break line?
            if not c or c == '\n' or col >= self.width:
                # retreat to last safe break point if we found one
                if safe:
                    self.doc.set_point(safe)
                break

    def frame_point(self,
            preferred_top: Location,
            margin_top = 4,
            margin_bottom = 4,
            preferred_row_fraction = 0.4
            ):
        """
        Frame the point with a list of row start locations.
        Start by finding a newline before the earliest
        possible top of the screen.
        This is one of: the start of the document;
        row newlines before the point;
        or one newline before row*cols displayed characters;
        whichever comes first.
        Calculate line break locations from there until
        we pass the point.
        If we encounter the preferred top of screen beforehand,
        use that as the start of the screen.
        If possible, adjust the start so that the point
        is within the preferred row range.
        If we don't find the preferred top of screen,
        set the top using a preferred row offset.
        Continue calculating line breaks as needed until
        we have row of them.
        """

        # find a safe place to start framing
        pt = self.doc.get_point()
        newlines = 0
        chars = 0
        loc = self.doc.get_point()
        while True:
            self.doc.find_char_backward('\n')
            newlines += 1
            chars += len(self.doc.slice(self.doc.get_point(), loc))
            loc = self.doc.get_point()
            if (
                self.doc.get_point() == self.doc.get_start()
                or newlines == self.height
                or chars >= self.height * self.width
            ):
                break
            self.doc.move_point(-1)     # skip before the newline

        # find line breaks until we reach the point
        breaks: list[Location] = []
        found = False
        while not found:
            breaks.append(loc)
            self.next_wrap()
            found = self.doc.span_contains(pt, loc, self.doc.get_point())
            loc = self.doc.get_point()
        breaks.append(loc)
        # the point is in the final span
        k = len(breaks)-1

        # choose row to start the screen
        try:
            # if preferred_top is a break, orient relative to that
            s = breaks[:k+1].index(preferred_top)
            s = min(
                # k - s <= self.height - margin_bottom
                max(s, k - self.height + margin_bottom),
                # k - s >= margin_top;  s >= 0
                max(0, k - margin_top)
            )
        except ValueError:
            # otherwise put point a reasonable way down the screen
            s = max(0, k - int(preferred_row_fraction * self.height))

        breaks = breaks[s:]
        while len(breaks) <= self.height and self.doc.get_point() != self.doc.get_end():
            self.next_wrap()
            breaks.append(self.doc.get_point())

        self.doc.set_point(pt)
        return breaks[:self.height+1]

    def refresh(self, scr: window, last_top: Location) -> Location:
        pt = self.doc.get_point()

        breaks = self.frame_point(last_top)
        top = breaks[0]

        cursor = None
        scr.clear()

        self.doc.set_point(top)
        for y in range(len(breaks)-1):
            try:
                scr.move(y, 0)
            except:
                print(f"move failed for {y}")
            x = 0
            while self.doc.get_point() != breaks[y+1]:
                if self.doc.get_point() == pt:
                    cursor = scr.getyx()

                ch = ord(self.doc.next_char())
                if 32 <= ch < 127:
                    if x < self.width-1:
                        scr.addch(ch)   # TODO tab, nl etc
                    else:
                        scr.insch(ch)   # TODO tab, nl etc
                x += 1

        #TODO this should always be found
        assert cursor
        scr.move(*cursor)

        self.doc.set_point(pt)
        scr.refresh()

        return top

"""
TODO control and meta key map

char/word/line/page/doc forward/backward
del char/word forward/backward

help
goto line number

@
A   select all / or start of line
B
C   copy
D   delete (meta: word)
E   end of line
F   find forward
G   bell / find again
H   backspace (meta: word)
I
J
K   cut line
L
M   enter
N
O
P
Q
R   find backward (or P - previous)
S   save
T
U
V   paste
W
X   cut
Y   redo
Z   undo
[   meta (escape)
\
]
^
_
"""
def main_loop(stdscr):

    stdscr.scrollok(False)
    curses.curs_set(2)
    height, width = stdscr.getmaxyx()
    display = Display(doc, height, width)

    top = doc.get_start()

    while True:
        top = display.refresh(stdscr, top)
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
