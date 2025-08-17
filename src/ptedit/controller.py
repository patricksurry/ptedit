import curses
from curses import window
from typing import Callable
from .piecetable import PieceTable
from .location import Location

whitespace = ' \t\n'

KeyFn = Callable[['Controller'],None]
KeyMap = dict[int, KeyFn]

class Controller:
    def __init__(self,
            doc: PieceTable,
            height: int,
            width: int,
            fname='',
            control_keys: KeyMap = {},
            meta_keys: KeyMap = {},
            guard_rows=4,
            preferred_row=0,
            tab=8):
        self.doc = doc
        self.height = height-1      # save last line for status
        self.width = width
        self.fname = fname

        # keymap
        self.control_keys = control_keys
        self.meta_keys = meta_keys

        # layout options
        self.tab = tab
        self.guard_rows = guard_rows
        self.preferred_row = preferred_row or int(0.4*height)
        self.preferred_col = 0
        self.preferred_top = self.doc.get_point() # top-left of screen

        # state
        self.mark: Location|None = None
        self.overwrite_mode = False
        self.meta_mode = False
        self.isearch_direction = 0      # -1 is backward, 1 is forward
        self.is_column_sticky = True    # sticky col for vertical navigation

    def key_handler(self, key: int):
        """Handle an ascii keypress"""
        if self.meta_mode:
            fn = self.meta_keys.get(key)
            if fn:
                fn(self)
            else:
                self.show_error(f'Unmapped meta key {key}')
            self.meta_mode = False
            return

        if 32 <= key < 127:
            # printable ascii keys insert themselves
            fn = Controller.insert
        else:
            fn = self.control_keys.get(key)

        if fn == Controller.insert:
            fn(self, key)
        elif fn:
            # is isearch active?
            if self.isearch_direction != 0 and fn not in (
                    Controller.isearch_forward,
                    Controller.isearch_backward,
                    Controller.delete_backward_char,
                ):
                # meta key cancels search and is not processed
                if fn == Controller.toggle_meta:
                    self._isearch_quit(True)
                    return
                # other actions terminate search but are still executed
                self._isearch_quit()
            fn(self)
        else:
            self.show_error(f'Unmapped key {key}')

    def save(self):
        if self.fname:
            open(self.fname, 'w').write(self.doc.data)

    def quit(self):
        self.doc = None         # TODO flag main to exit

    def squash(self):
        self.doc = PieceTable(self.doc.data)

    def show_error(self, msg: str):
        #TODO save message for status bar
        curses.flash()

    def toggle_meta(self):
        self.meta_mode = not self.meta_mode

    ### Navigation commands

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

    def isearch_forward(self):
        self._isearch_trigger(1)

    def isearch_backward(self):
        self._isearch_trigger(-1)

    def _isearch_quit(self, cancel=False):
        self.isearch_direction = 0
        if cancel:
            self.doc.set_point(self.search_pt)

    def _isearch_insert(self, c: str):
        self.search_text += c
        self._isearch_trigger(reset=True)

    def _isearch_delete(self):
        self.search_text = self.search_text[:-1]
        self._isearch_trigger(reset=True)

    def _isearch_trigger(self, direction=0, reset=False):
        if reset:
            self.doc.set_point(self.search_pt)

        first = self.isearch_direction == 0

        if direction:
            self.isearch_direction = direction

        if first:
            # remember where we started
            self.search_pt = self.doc.get_point()
            # TODO remember past text
            self.search_text = ''
        elif self.search_text:
            # search from current point
            if self.isearch_direction == 1:
                self.doc.find_forward(self.search_text)
            else:
                self.doc.find_backward(self.search_text)
        else:
            # TODO recycle past text if available
            self.show_error("Empty search")
            # TODO quit isearch mode?

    ### Editing commands

    def toggle_overwrite(self):
        self.overwrite_mode = not self.overwrite_mode

    def insert(self, ch):
        c = chr(ch)
        if self.isearch_direction:
            self._isearch_insert(c)
        elif self.overwrite_mode:
            self.doc.insert(c)
        else:
            self.doc.replace(c)

    def delete_forward_char(self):
        self.doc.delete(1)

    def delete_backward_char(self):
        if self.isearch_direction:
            self._isearch_delete()
        else:
            self.doc.delete(-1)

    def undo(self):
        self.doc.undo()

    def redo(self):
        self.doc.redo()

    ### Internal beginning-of-line routines

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

    ### Screen update routines

    def find_top(self):
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
            if self.doc.get_point() == self.preferred_top:
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

        self.preferred_top = self.doc.get_point()

    def paint(self, scr: window):
        """
        Paint the buffer to the screen, returning the new top-left location.
        Leaves point unchanged.
        """
        pt = self.doc.get_point()
        self.find_top()         # move point to show at top-left of screen
        cursor = None           # the y,x of the point

        scr.clear()

        ch = 0                  # in case doc is empty, when there is no prior char
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

        doc_nl = self.doc.data.count('\n')
        pt_nl = Location.span_data(self.doc.get_start(), pt).count('\n')
        dirty = ('*' if self.doc.edit_stack.sp else '') + f'{self.fname}'
        status = "  ".join([
            f" {dirty}",
            f"xy {cursor[1]},{cursor[0]}",
            f"pos {pt.position()}/{self.doc.length}",
            f"lns {pt_nl}/{doc_nl}",
            f"pcs {pt.chain_length()}/{self.doc.get_end().chain_length()}",
            f"eds {self.doc.edit_stack.sp}/{len(self.doc.edit_stack.edits)}",
        ])
        status += " " * (self.width - len(status))
        try:
            scr.addstr(self.height, 0, status, curses.A_REVERSE)
        except curses.error:
            pass

        scr.move(*cursor)
        scr.refresh()

        self.doc.set_point(pt)
