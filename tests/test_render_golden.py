import os
from pathlib import Path

from ptedit import display, document
from ptedit.screen import Screen


GOLDEN_DIR = Path(__file__).parent / 'golden'
ALICE_FLOW = (Path(__file__).parent / 'alice1flow.asc').read_text()
UPDATE = os.environ.get('UPDATE_GOLDENS') == '1'


class RecordingScreen(Screen):
    """Captures every put() as (ch, highlight) for byte-level golden comparison."""
    def __init__(self, height: int, width: int):
        # Screen is a @dataclass; call super().__init__ with positional args.
        super().__init__(height, width)
        self.events: list[tuple[int, bool]] = []

    def put(self, ch: int, highlight: bool = False):
        self.events.append((ch, highlight))

    def encode(self) -> bytes:
        # Two bytes per cell: char, then highlight flag (0/1).
        out = bytearray()
        for ch, hi in self.events:
            out.append(ch & 0xff)
            out.append(1 if hi else 0)
        return bytes(out)


def assert_golden(name: str, payload: bytes):
    path = GOLDEN_DIR / f'{name}.bin'
    if UPDATE or not path.exists():
        path.write_bytes(payload)
        return
    expected = path.read_bytes()
    assert payload == expected, (
        f'golden {name} mismatch: got {len(payload)} bytes, '
        f'expected {len(expected)} bytes; '
        f"re-run with UPDATE_GOLDENS=1 to refresh"
    )


def _make_display() -> tuple[display.Display, document.Document, RecordingScreen]:
    doc = document.Document(ALICE_FLOW)
    scr = RecordingScreen(24, 80)
    dpy = display.Display(doc, scr)
    return dpy, doc, scr


def test_golden_open_paint():
    """Initial paint at start of doc."""
    dpy, doc, scr = _make_display()
    dpy.paint()
    assert_golden('open_paint', scr.encode())


def test_golden_pgdn_pgup():
    """Page down twice, page up twice."""
    dpy, doc, scr = _make_display()
    dpy.paint()
    for _ in range(2):
        dpy.layout.move_page_forward()
        dpy.paint()
    for _ in range(2):
        dpy.layout.move_page_backward()
        dpy.paint()
    assert_golden('pgdn_pgup', scr.encode())


def test_golden_insert_typing():
    """Type 'hello' at start, redrawing after each keystroke."""
    # Document.insert() takes a str; convert each byte from b'hello' via chr().
    dpy, doc, scr = _make_display()
    dpy.paint()
    for ch in b'hello':
        doc.insert(chr(ch))
        dpy.paint()
    assert_golden('insert_typing', scr.encode())


def test_golden_end_to_top():
    """Navigate to end, then page up several times."""
    dpy, doc, scr = _make_display()
    doc.set_point_end()
    dpy.paint()
    for _ in range(5):
        dpy.layout.move_page_backward()
        dpy.paint()
    assert_golden('end_to_top', scr.encode())


def test_golden_sticky_top():
    """Small cursor moves within the window must NOT scroll (sticky top).

    Move to a mid-doc position so the screen is stable, then step forward
    one visual line five times.  Each move keeps the cursor well within the
    window (rows=23, guard=3) so the top anchor must stay fixed: the screen
    content of row 0 should be identical across all six paints.
    """
    dpy, doc, scr = _make_display()
    # Put cursor 5 pages in so there is room above and below.
    for _ in range(5):
        dpy.layout.move_page_forward()
    dpy.paint()
    first_top = dpy.top_loc          # record anchor after initial paint
    for _ in range(5):
        dpy.layout.move_line_forward()
        dpy.paint()
        assert dpy.top_loc == first_top, (
            f"sticky top violated: top moved from {first_top} to {dpy.top_loc}"
        )
    assert_golden('sticky_top', scr.encode())
