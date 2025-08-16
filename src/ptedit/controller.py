import curses
from curses import wrapper, window
from os import path

from .piecetable import PieceTable
from .location import Location

whitespace = ' \t\n'

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
        self.preferred_col = 0

        # state
        self.insert_mode = True
        self.meta_mode = False
        self.is_column_sticky = True

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

    def move_forward_word(self):
        self.doc.find_char_forward(whitespace)
        self.doc.find_not_char_forward(whitespace)

    def move_backward_word(self):
        self.doc.find_not_char_backward(whitespace)
        self.doc.find_char_backward(whitespace)

    def move_forward_para(self):
        while self.doc.get_point() != self.doc.get_end():
            self.doc.find_char_forward('\n')
            self.doc.move_point(1)
            if self.doc.get_char() in whitespace:
                break
        self.doc.find_not_char_forward(whitespace)

    def move_backward_para(self):
        self.doc.find_not_char_backward(whitespace)
        while self.doc.get_point() != self.doc.get_start():
            self.doc.find_char_backward('\n')
            if self.doc.get_char() in whitespace:
                break
            self.doc.move_point(-1)
        self.doc.find_not_char_forward(whitespace)

    def move_start_line(self):
        self.clamp_to_bol()

    def move_end_line(self):
        self.clamp_to_bol()
        self.bol_to_next_bol()
        self.move_backward_char()

    def move_forward_line(self):
        self.clamp_to_bol()
        self.bol_to_next_bol()
        self.bol_to_preferred_col()

    def move_backward_line(self):
        self.clamp_to_bol()
        self.bol_to_prev_bol()
        self.bol_to_preferred_col()

    def move_forward_page(self):
        self.clamp_to_bol()
        for _ in range(self.height):
            self.bol_to_next_bol()
        self.bol_to_preferred_col()

    def move_backward_page(self):
        self.clamp_to_bol()
        for _ in range(self.height):
            self.bol_to_prev_bol()
        self.bol_to_preferred_col()

    def move_start(self):
        self.doc.set_point(self.doc.get_start())

    def move_end(self):
        self.doc.set_point(self.doc.get_end())

    def delete_forward_char(self):
        self.doc.delete(1)

    def delete_backward_char(self):
        self.doc.delete(-1)

    def undo(self):
        self.doc.undo()

    def redo(self):
        self.doc.redo()

    def _bol_forward(self, max_col: int | None = None):
        """
        Advance point to the next soft-break location,
        i.e. just past a newline/whitespace/hyphen or end of doc.
        """
        safe: Location | None = None
        col = 0
        while max_col is None or col <= max_col:
            c = self.doc.next_char()
            if not c or c in ' -\t\n':
                safe = self.doc.get_point()
            col += 1 if c != '\t' else (self.tab - (col % self.tab))
            # time to break line?
            if not c or c == '\n' or col >= self.width:
                # retreat to last safe break point if there was one
                # otherwise leave the point unchanged
                if safe:
                    self.doc.set_point(safe)
                break
        if max_col is not None:
            self.doc.move_point(-1)

    def bol_to_next_bol(self):
        self._bol_forward()

    def bol_to_preferred_col(self):
        self._bol_forward(self.preferred_col)
        self.is_column_sticky = False

    def clamp_to_bol(self):
        """
        Move the point back to prior bol.
        Unlike bol_to_prev_bol this is a no-op if we're already at BOL
        """
        pt = self.doc.get_point()

        self.doc.find_char_backward('\n')
        while True:
            loc = self.doc.get_point()
            if loc == pt:
                break
            self.bol_to_next_bol()
            if Location.span_contains(pt, loc, self.doc.get_point()):
                self.doc.set_point(loc)
                break

    def bol_to_prev_bol(self):
        """
        Move from BOL to the previous BOL.
        This is a no-op at the document start.
        """

        pt = self.doc.get_point()
        if pt == self.doc.get_start():
            return

        self.doc.move_point(-1)
        self.doc.find_char_backward('\n')
        while True:
            loc = self.doc.get_point()
            self.bol_to_next_bol()
            if pt == self.doc.get_point():
                break
        self.doc.set_point(loc)

    def bol_to_bol_length(self):
        """
        Count the number of characters from point (at BOL)
        to the next BOL
        """
        pt = self.doc.get_point()
        self.bol_to_next_bol()
        n = Location.span_length(pt, self.doc.get_point())
        self.doc.set_point(pt)
        return n

    def find_top(self, preferred_top: Location):
        """
        Move the point to the top left of the screen,
        anchoring to preferred_top if possible.
        """
        #TODO this alayws treats end-of-doc as new line even when there isn't
        # an actual newline
        self.clamp_to_bol()
        for k in range(self.height):
            self.bol_to_prev_bol()
            if k == self.preferred_row:
                fallback = self.doc.get_point()
            if self.doc.get_point() == preferred_top:
                break

        # found top?
        if k < self.height-1:
            # too close to point?
            while k < self.guard_rows:
                self.bol_to_prev_bol()
                k += 1

            # found top too far from point?
            while k > self.height - self.guard_rows:
                self.bol_to_next_bol()
                k -= 1
        else:
            self.doc.set_point(fallback)

    def paint(self, scr: window, last_top: Location) -> Location:
        """
        Paint the buffer to the screen, returning the new top-left location.
        Leaves point unchanged.
        """
        pt = self.doc.get_point()
        top = self.find_top(last_top)
        cursor = None           # the y,x of the point

        scr.clear()
        y = 0
        while y < self.height:
            x = 0
            scr.move(y, x)
            for _ in range(self.bol_to_bol_length()):
                if self.doc.get_point() == pt:
                    cursor = (y,x)

                c = self.doc.next_char()
                ch = ord(c) if c else None
                if 32 <= ch < 127:
                    if x < self.width-1:
                        scr.addch(ch)
                    else:
                        scr.insch(ch)
                    x += 1
                elif ch == 9:       # tab
                    k = self.tab - (x % self.tab)
                    x += k
                    while k:
                        scr.addch(32)
                        k -= 1

            # last line without trailing newline?
            if self.doc.get_point() == self.doc.get_end() and ch != 10:
                x += 1
                break
            y += 1

        if not cursor:
            cursor = (y,x)

        # update preferred column unless this was a non-sticky cursor movement
        if self.is_column_sticky:
            self.preferred_col = cursor[1]
        else:
            self.is_column_sticky = True

        scr.move(*cursor)
        scr.refresh()

        self.doc.set_point(pt)

        return top


def ctrl(c):
    return ord(c[0].upper()) - ord('@')

control_keys = {
    curses.KEY_LEFT: Controller.move_backward_char,
    curses.KEY_RIGHT: Controller.move_forward_char,
    curses.KEY_UP: Controller.move_backward_line,
    curses.KEY_DOWN: Controller.move_forward_line,
    curses.KEY_BACKSPACE: Controller.delete_backward_char,
    curses.KEY_ENTER: Controller.insert,
    127: Controller.delete_backward_char,
    ctrl('A'): Controller.move_start_line,
    ctrl('B'): Controller.move_backward_word,
    ctrl('F'): Controller.move_forward_word,
    ctrl('E'): Controller.move_end_line,
    ctrl('D'): Controller.delete_forward_char,
    ctrl('I'): Controller.insert,       # tab
    ctrl('J'): Controller.insert,       # newline
    ctrl('Y'): Controller.redo,
    ctrl('Z'): Controller.undo,
    ctrl('['): Controller.toggle_meta,  # escape
}

meta_keys = {
    ctrl('['): Controller.toggle_meta, # escape
    ord('a'): Controller.move_backward_page,
    ord('b'): Controller.move_backward_para,
    ord('f'): Controller.move_forward_para,
    ord('e'): Controller.move_forward_page,
    ord('A'): Controller.move_start,
    ord('E'): Controller.move_end,
    ord('o'): Controller.toggle_insert,
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
#        top = controller.refresh(stdscr, top)
        top = controller.paint(stdscr, top)
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
