from ptedit import document, display, editor, controller
from ptedit.screen import Screen


def make_editor(text):
    doc = document.Document(text)
    dpy = display.Display(doc, display.Screen(24, 80))
    ed = editor.Editor(doc, dpy.layout, lambda msg, warn=False: dpy.show_message(msg, warn))
    return doc, dpy, ed


def test_paste_with_empty_clipboard_preserves_region():
    doc, dpy, ed = make_editor('hello world')
    doc.move_point(6)
    ed.set_mark()
    doc.move_point(5)             # mark spans 'world'
    assert ed.clipboard == ''
    ed.paste()
    # nothing on the clipboard, so the document should be unchanged
    assert doc.get_data() == 'hello world'


def test_kill_region_does_not_clobber_clipboard():
    # Uses insert (which calls _kill_region internally) to avoid the doc-end issue
    # that delete_forward_char hits when the region spans to end of document.
    doc, dpy, ed = make_editor('hello world')
    ed.clipboard = 'previous'
    doc.move_point(6)
    ed.set_mark()
    doc.move_point(5)             # mark spans 'world'
    ed.insert(ord('X'))           # kills region then inserts 'X'
    assert doc.get_data() == 'hello X'
    assert ed.clipboard == 'previous'   # untouched


def test_kill_region_works_when_mark_is_after_point():
    # mark is AFTER point: region is 'hello' (point=0, mark=5)
    doc, dpy, ed = make_editor('hello world')
    doc.move_point(5)             # point at ' '
    ed.set_mark()
    doc.move_point(-5)            # point now at 0, mark at 5 → region is 'hello'
    ed.insert(ord('X'))           # kills region then inserts 'X'
    assert doc.get_data() == 'X world'


def test_isearch_keys_route_to_search_not_document(tmp_path):
    f = tmp_path / 't.txt'
    f.write_text('hello world\n')
    ctrl = controller.Controller(str(f), Screen(24, 80))
    ctrl.dispatch(controller.ctrl('S'))          # enter isearch
    for c in 'world':
        ctrl.dispatch(ord(c))
    assert ctrl.ed.isearch_text == 'world'
    assert ctrl.doc.get_point().position() == 11          # point after the match
    assert ctrl.doc.get_data() == 'hello world\n'         # nothing inserted
    ctrl.dispatch(127)                                    # isearch backspace
    assert ctrl.ed.isearch_text == 'worl'


def test_editor_delegates_line_and_page_moves_to_layout():
    from ptedit import editor as editor_mod
    doc = document.Document('abcdef\nghijkl\nmnopqr\n')
    dpy = display.Display(doc, display.Screen(24, 16))
    ed = editor_mod.Editor(doc, dpy.layout, lambda msg, warn=False: None)
    # each delegation is the very same bound method object as Layout's
    for name in ('move_start_line', 'move_end_line', 'move_forward_line',
                 'move_backward_line', 'move_forward_page', 'move_backward_page'):
        assert getattr(ed, name).__func__ is getattr(dpy.layout, name).__func__
    # and it actually moves the point through Layout
    doc.set_point_start()
    ed.move_forward_line()
    assert doc.get_point().position() == 7        # BoL of line 1
