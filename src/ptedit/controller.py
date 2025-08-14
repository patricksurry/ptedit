import curses
from curses import wrapper, window
from os import path

from .piecetable import PieceTable
from .location import Location

#TODO maintain a 'place' mark for output, so can scan chars
# to count row/col and find where place=point

class Controller:
    def __init__(self, doc: PieceTable,
            height: int,
            width: int,
            guard_rows=4,
            preferred_row=0,
            tab=8):
        self.doc = doc
        self.height = height
        self.width = width

        # layout options
        self.tab = tab
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row or int(0.4*height)

        # state
        self.insert_mode = True
        self.meta_mode = False

    def insert(self, ch):
        c = chr(ch)
        if self.insert_mode:
            self.doc.insert(c)
        else:
            self.doc.replace(c)

    def toggle_insert(self):
        self.insert_mode = not self.insert_mode

    def toggle_meta(self):
        self.meta_mode = not self.meta_mode

    def move_forward_char(self):
        self.doc.move_point(1)

    def move_backward_char(self):
        self.doc.move_point(-1)

    def move_forward_line(self):
        self.doc.move_point(40)

    def move_backward_line(self):
        self.doc.move_point(-40)

    def delete_forward_char(self):
        self.doc.delete(1)

    def delete_backward_char(self):
        self.doc.delete(-1)

    def undo(self):
        self.doc.undo()

    def redo(self):
        self.doc.redo()

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
        loc = pt = self.doc.get_point()
        newlines = 0
        chars = 0
        while True:
            self.doc.find_char_backward('\n')
            newlines += 1
            chars += len(Location.span_data(self.doc.get_point(), loc))
            loc = self.doc.get_point()
            if (
                loc == self.doc.get_start()
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
            found = Location.span_contains(pt, loc, self.doc.get_point())
            loc = self.doc.get_point()
        breaks.append(loc)
        # the point is in the final span
        k = len(breaks)-1

        # choose row to start the screen
        try:
            # if preferred_top is a break, orient relative to that
            s = breaks[:k+1].index(preferred_top)
            s = min(
                # k - s <= height - guard_rows
                max(s, k - self.height + self.guard_rows),
                # k - s >= guard_rows;  s >= 0
                max(0, k - self.guard_rows)
            )
        except ValueError:
            # otherwise put point a reasonable way down the screen
            s = max(0, k - int(self.preferred_row))

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

def CTRL(c):
    return ord(c[0].upper()) - ord('@')

control_keys = {
    curses.KEY_LEFT: Controller.move_backward_char,
    curses.KEY_RIGHT: Controller.move_forward_char,
    curses.KEY_UP: Controller.move_backward_line,
    curses.KEY_DOWN: Controller.move_forward_line,
    curses.KEY_BACKSPACE: Controller.delete_backward_char,
    curses.KEY_ENTER: Controller.insert,
    127: Controller.delete_backward_char,
    CTRL('D'): Controller.delete_forward_char,
    CTRL('I'): Controller.insert,       # tab
    CTRL('J'): Controller.insert,       # newline
    CTRL('O'): Controller.toggle_insert,
    CTRL('Y'): Controller.redo,
    CTRL('Z'): Controller.undo,
    CTRL('['): Controller.toggle_meta,  # escape
}

meta_keys = {
    CTRL('['): Controller.toggle_meta, # escape
    ord('y'): Controller.redo,
    ord('z'): Controller.undo,
}

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
    controller = Controller(doc, height, width)

    top = doc.get_start()

    while True:
        top = controller.refresh(stdscr, top)
        key = stdscr.getch()
        if controller.meta_mode:
            if key in meta_keys:
                fn = meta_keys[key]
                fn(controller)
            else:
                curses.flash()
            controller.meta_mode = False
        elif key in control_keys:
            fn = control_keys[key]
            if fn == Controller.insert:
                fn(controller, key)
            else:
                fn(controller)
        elif 32 <= key < 127:
            controller.insert(key)
        else:
            curses.flash()

if __name__ == "__main__":
    alice = open(path.join(path.dirname(__file__), '../../tests/alice1flow.asc')).read()
    doc = PieceTable(alice)
    doc.find_char_forward('\n')
    print(doc.get_point())

    wrapper(main_loop)
