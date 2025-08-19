import curses
from .controller import Controller


def ctrl(c):
    """
    Note that control-keys are case-insenstive, i.e. shift doesn't matter.
    In fact only the lower five bits matter, so C-@ and C-space are normally equivalent.
    """
    return ord(c[0]) & 0b11111

# note curses won't see all control keys since zsh is intercepting some
# for example, to use ctrl-S/ctrl-Q (normally xon/xoff) disable flow control
# on OS X add `stty -ixon` to your .zshrc file
# to allow ctrl-O on OS X add `stty discard undef`

# These are normal ascii key-presses that trigger editing commands
# The normal printable characters (ascii 32-126 inclusive) insert themselves
# Any ascii value not otherwise mentioned will show as an error
# Normally these are generated as control keys, but you can also
# map 8-bit ascii values (>127) if your keyboard can generate them
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
    ctrl('_'): Controller.squash,
    ctrl('S'): Controller.isearch_forward,
    ctrl('R'): Controller.isearch_backward,
    ctrl('O'): Controller.toggle_overwrite,
}


# These are keys entered after an initial Escape (C-[) is entered
# Any valid ascii value can be used, e.g. a, A, C-A are all distinct options
meta_keys = {
    ctrl('['): Controller.clear_mark,
    ord('a'): Controller.move_backward_page,
    ord('b'): Controller.move_backward_para,
    ord('f'): Controller.move_forward_para,
    ord('e'): Controller.move_forward_page,
    ord('A'): Controller.move_start,
    ord('E'): Controller.move_end,
    ord('m'): Controller.set_mark,
    ord('s'): Controller.save,
    ord('q'): Controller.quit,
    ord('y'): Controller.redo,
    ord('z'): Controller.undo,
}

"""
other keys:

set mark C-' ' == C-@
del char/word forward/backward
cut line C-K
help
goto line number
select all, e.g. C-A
cut/copy/paste C-C/C-X/C-V
find C-F/C-G/C-R or P for back
bksp C-H

C-</|  0x1c
C-=]}  0x1d
C->^~  0x1e
C-?_DEL 0x1f
"""
