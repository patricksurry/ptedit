from ptedit import document, display, editor


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
