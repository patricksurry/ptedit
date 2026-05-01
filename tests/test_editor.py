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
