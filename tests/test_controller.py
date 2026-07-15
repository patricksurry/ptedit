import curses
import re

import pytest

from ptedit import controller


def test_keyname_formats_codes():
    assert controller.keyname(ord('a')) == 'a'
    assert controller.keyname(ord('?')) == '?'
    assert controller.keyname(9) == 'C-I'          # tab is control-I
    assert controller.keyname(1) == 'C-A'
    assert controller.keyname(27) == 'Esc'
    assert controller.keyname(32) == 'Space'
    assert controller.keyname(127) == 'Del'
    assert controller.keyname(curses.KEY_LEFT) == 'Left'
    assert controller.keyname(curses.KEY_ENTER) == 'Enter'
    assert controller.keyname(999999) == '<999999>'


from ptedit.screen import Screen


def _ctrl(tmp_path, text='hello world\n'):
    f = tmp_path / 't.txt'
    f.write_text(text)
    return controller.Controller(str(f), Screen(24, 80))


def test_register_duplicate_name_raises(tmp_path):
    """Two callables that kebab-case to the same name must fail loudly at
    registration rather than one silently shadowing the other."""
    c = _ctrl(tmp_path)
    with pytest.raises(AssertionError):
        c.register_commands([c.save])          # 'save' already registered


def test_registry_covers_every_binding(tmp_path):
    c = _ctrl(tmp_path)
    for km, mode in c.modes.items():
        for key, name in mode.bindings.items():
            assert name in c.commands, f'{km.name}:{name} unregistered'


def test_normal_printable_self_inserts(tmp_path):
    c = _ctrl(tmp_path, '')
    c.dispatch(ord('x'))
    assert c.doc.get_data() == 'x'
    assert c.mode_stack[-1] is controller.KeyMode.NORMAL


def test_isearch_printable_extends_search(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('S'))
    assert c.mode_stack[-1] is controller.KeyMode.ISEARCH
    for ch in 'world':
        c.dispatch(ord(ch))
    assert c.ed.isearch_text == 'world'
    assert c.doc.get_data() == 'hello world\n'         # nothing inserted


def test_isearch_unbound_key_exits_and_re_dispatches(tmp_path):
    # An arrow in isearch exits search (leaving point) AND performs the motion.
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('S'))
    for ch in 'world':
        c.dispatch(ord(ch))
    pos = c.doc.get_point().position()                 # after the 'world' match
    c.dispatch(curses.KEY_LEFT)                         # unbound in ISEARCH
    assert c.ed.isearch_dir is None                    # search exited
    assert c.mode_stack[-1] is controller.KeyMode.NORMAL
    assert c.doc.get_point().position() == pos - 1     # motion happened


def test_meta_is_one_shot(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                   # enter META
    assert c.mode_stack[-1] is controller.KeyMode.META
    c.dispatch(ord('m'))                               # set-mark
    assert c.ed.mark is not None
    assert c.mode_stack[-1] is controller.KeyMode.NORMAL   # auto-returned


def test_meta_unknown_key_returns_to_normal(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))
    c.dispatch(ord('Z'))                               # unbound in META
    assert c.mode_stack[-1] is controller.KeyMode.NORMAL
    assert 'No binding for Esc Z' in c.dpy.message     # prefix included


def test_help_shows_and_dismisses(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                  # META
    c.dispatch(ord('?'))                              # describe-bindings
    assert c.mode_stack[-1] is controller.KeyMode.HELP
    lines = c._help_lines()
    assert any('move-forward-char' in ln for ln in lines)
    # page forward through every page; the key past the last page dismisses
    for _ in range(c._help_pages()):
        c.dispatch(ord('x'))
    assert c.mode_stack[-1] is controller.KeyMode.NORMAL
    assert c.doc.get_data() == 'hello world\n'        # paging keys not inserted


def test_help_lines_fit_the_screen_at_various_widths(tmp_path):
    """Every rendered line fits the width by construction (columns sized to
    the terminal), and a page never exceeds dpy.rows — at wide and narrow."""
    for w in (80, 40, 20, 8):
        f = tmp_path / f't{w}.txt'
        f.write_text('hello world\n')
        c = controller.Controller(str(f), Screen(24, w))
        lines = c._help_lines()
        assert all(len(ln) <= w for ln in lines), w
        assert len(lines) <= c.dpy.rows, w


def _page_capacity(c):
    ncols, _, _ = c._help_grid()
    return ncols * c.dpy.rows


def test_help_paging_covers_every_binding_without_loss(tmp_path):
    """Paging chunks the entry list, so the pages hold every binding with room
    to spare — none dropped — and full command names appear untruncated at 80."""
    c = _ctrl(tmp_path)
    assert c._help_pages() * _page_capacity(c) >= len(c._help_entries())
    blob = '\n'.join(c._help_lines())                 # page 0
    for cmd in ('move-forward-char', 'save', 'describe-bindings',
                'isearch-forward', 'delete-backward-char'):
        assert cmd in blob, cmd                       # full name, untruncated at 80


def test_help_paging_on_narrow_screen_spans_multiple_pages(tmp_path):
    """A narrow terminal fits fewer bindings per page, so help spills onto
    additional pages; the pages still cover the whole entry list."""
    f = tmp_path / 't.txt'
    f.write_text('hello world\n')
    c = controller.Controller(str(f), Screen(24, 20))   # 1 column
    assert c._help_pages() >= 2
    assert c._help_pages() * _page_capacity(c) >= len(c._help_entries())


def test_help_page_back_clamps_at_zero(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))
    c.dispatch(ord('?'))
    assert c.help_page == 0
    c.dispatch(curses.KEY_LEFT)                        # page back at first page
    assert c.help_page == 0
    assert c.mode_stack[-1] is controller.KeyMode.HELP  # still in help


def test_meta_chord_shown_with_esc_prefix(tmp_path):
    c = _ctrl(tmp_path)
    chords = {cmd: chord for chord, cmd in c._help_entries()}
    assert chords['paste'] == 'Esc v'                 # META key carries its prefix
    assert chords['clear-mark'] == 'Esc Esc'
    assert chords['move-forward-char'] == 'Right'     # NORMAL key shown bare


def test_unbound_error_names_help_chord(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('G'))                  # C-G: unbound in NORMAL
    assert 'No binding for C-G' in c.dpy.message
    assert c.dpy.message.rstrip().endswith('Esc ? for help')   # hint right-justified


def test_user_facing_text_is_ascii(tmp_path):
    """The screen renders one iso-8859-1 byte per char, so codepoints > 255
    (e.g. an em-dash) can't display — keep messages and help ASCII."""
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                  # META
    c.dispatch(ord('Z'))                              # unmapped -> beep message
    assert c.dpy.message.isascii(), repr(c.dpy.message)
    assert all(ln.isascii() for ln in c._help_lines())
