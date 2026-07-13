import curses

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


def test_registry_covers_every_binding(tmp_path):
    c = _ctrl(tmp_path)
    for mode in c.modes.values():
        for key, name in mode.bindings.items():
            assert name in c.commands, f'{mode.name.name}:{name} unregistered'


def test_normal_printable_self_inserts(tmp_path):
    c = _ctrl(tmp_path, '')
    c.dispatch(ord('x'))
    assert c.doc.get_data() == 'x'
    assert c.stack[-1].name is controller.KeyMode.NORMAL


def test_isearch_printable_extends_search(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('S'))
    assert c.stack[-1].name is controller.KeyMode.ISEARCH
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
    assert c.stack[-1].name is controller.KeyMode.NORMAL
    assert c.doc.get_point().position() == pos - 1     # motion happened


def test_meta_is_one_shot(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                   # enter META
    assert c.stack[-1].name is controller.KeyMode.META
    c.dispatch(ord('m'))                               # set-mark
    assert c.ed.mark is not None
    assert c.stack[-1].name is controller.KeyMode.NORMAL   # auto-returned


def test_meta_unknown_key_returns_to_normal(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))
    c.dispatch(ord('Z'))                               # unbound in META
    assert c.stack[-1].name is controller.KeyMode.NORMAL
    assert 'No action' in c.dpy.message


def test_help_shows_and_dismisses(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('['))                  # META
    c.dispatch(ord('?'))                              # describe-bindings
    assert c.stack[-1].name is controller.KeyMode.HELP
    lines = c._help_lines()
    assert any('move-forward-char' in ln for ln in lines)
    c.dispatch(ord('x'))                              # any key dismisses
    assert c.stack[-1].name is controller.KeyMode.NORMAL
    assert c.doc.get_data() == 'hello world\n'        # dismiss key not inserted


def test_unbound_error_names_help_chord(tmp_path):
    c = _ctrl(tmp_path)
    c.dispatch(controller.ctrl('G'))                  # C-G: unbound in NORMAL
    assert 'No action' in c.dpy.message
    assert 'Esc ? for help' in c.dpy.message
