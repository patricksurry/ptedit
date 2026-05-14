from ptedit import document, layout
from ptedit.layout import Ladder
from ptedit.location import Location


def _locs(n: int) -> list[Location]:
    """Distinct, ordered Locations for ladder-mechanics tests."""
    from ptedit.document import Document
    d = Document('x' * (n * 2))
    out = []
    for i in range(n):
        d.set_point_start().move_point(i * 2)
        out.append(d.get_point())
    return out


def test_ladder_empty():
    lad = Ladder()
    assert not lad
    assert len(lad) == 0
    assert lad.top == 0


def test_ladder_append_and_iter():
    lad = Ladder()
    locs = _locs(5)
    for loc in locs:
        lad.append(loc)
    assert bool(lad)
    assert len(lad) == 5
    assert list(lad) == locs
    assert lad[0] == locs[0]
    assert lad[-1] == locs[-1]


def test_ladder_truncate():
    lad = Ladder()
    locs = _locs(5)
    for loc in locs:
        lad.append(loc)
    lad.truncate_to(2)
    assert list(lad) == locs[:2]


def test_ladder_reset():
    lad = Ladder()
    for loc in _locs(3):
        lad.append(loc)
    new_anchor = _locs(1)[0]
    lad.reset(new_anchor)
    assert list(lad) == [new_anchor]
    assert lad.top == 0


def test_ladder_drops_oldest_past_max():
    """Past MAX entries, oldest is discarded; top index follows."""
    lad = Ladder()
    locs = _locs(Ladder.MAX + 3)
    for loc in locs:
        lad.append(loc)
    assert len(lad) == Ladder.MAX
    assert list(lad) == locs[3:]


def test_bol():
    doc = document.Document('the big\t 012345678901234567890123456789 number')
    fmt = layout.Layout(doc, 24, 24, tab=4)

    assert doc.at_start()
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9 + 24
    fmt.bol_to_next_bol()
    assert doc.at_end(), f"{doc.get_point().position()}/{len(doc)}"


def test_format():
    doc = document.Document('the \tbig\t 012345678901234567890123456789\r\x01 number\x7f')
    fmt = layout.Layout(doc, 24, 24, tab=4)
    assert fmt.format_line()[0] == b'the \t\0\0\0big\t ' + bytes(11)
    assert fmt.format_line()[0] == b'012345678901234567890123'
    assert fmt.format_line()[0] == b'456789\x01M\x01A number\x027F' + bytes(4)


def test_column_for_offset():
    doc = document.Document('456789\r\x01 number\x7f')
    fmt = layout.Layout(doc, 24, 24, tab=4)
    line, col_map = fmt.format_line()
    # source data:   456789.. number.#
    #                012345678901234567890123
    # formatted:     456789^M^A number\7F#000    where # is 0 for eod
    assert line == b'456789\x01M\x01A number\x027F' + bytes(4)
    assert len(col_map) == len(doc) + 1     # +1 for eod
    assert col_map[0] == 0
    assert col_map[6] == 6
    assert col_map[7] == 8
    assert col_map[15] == 17
    assert col_map[16] == 20


def test_offset_for_column():
    doc = document.Document('456789\r\x01')
    fmt = layout.Layout(doc, 24, 24, tab=4)
    line, col_map = fmt.format_line()
    assert line == b'456789\x01M\x01A' + bytes(14)
    assert layout.Layout.offset_for_column(0, col_map) == 0
    assert layout.Layout.offset_for_column(5, col_map) == 5
    assert layout.Layout.offset_for_column(6, col_map) == 6  # ^
    assert layout.Layout.offset_for_column(7, col_map) == 6  # M
    assert layout.Layout.offset_for_column(8, col_map) == 7  # ^
    assert layout.Layout.offset_for_column(9, col_map) == 7  # A
    assert layout.Layout.offset_for_column(10, col_map) == 8  # eod
    assert layout.Layout.offset_for_column(99, col_map) == 8  # eod


def test_change_handler_truncates_at_edit():
    """Ladder entries within cols of the edit are dropped (rule 2: cols-margin)."""
    doc = document.Document('line 1\nline 2\nline 3\nline 4\nline 5\n')
    lay = layout.Layout(doc, 24, 24, 8)
    doc.watch(lay.change_handler)

    # Manually populate the ladder with BoL marks at positions 0, 7, 14, 21.
    bols = []
    for off in (0, 7, 14, 21):
        doc.set_point_start().move_point(off)
        bols.append(doc.get_point())
    for b in bols:
        lay.bol_ladder.append(b)
    assert len(lay.bol_ladder) == 4

    # Insert at pos 14 (start of 'line 3'): pure insertion, exclude_empty=True,
    # so remap returns loc unchanged. With cols=24 and edit_pos=14,
    # pos 0: 0+24=24 >= 14 → dropped immediately. All 4 entries dropped.
    doc.set_point_start().move_point(14)
    doc.insert('x')
    assert len(lay.bol_ladder) == 0


def test_change_handler_keeps_far_entries():
    """Ladder entries more than `cols` chars before edit survive."""
    doc = document.Document('line 1\nline 2\nline 3\nline 4\nline 5\n')
    lay = layout.Layout(doc, 4, 24)  # cols=4
    doc.watch(lay.change_handler)

    bols = []
    for off in (0, 7, 14, 21):
        doc.set_point_start().move_point(off)
        bols.append(doc.get_point())
    for b in bols:
        lay.bol_ladder.append(b)

    # Insert at pos 21 (start of 'line 4'). Pure insertion (exclude_empty=True),
    # remap returns loc unchanged. With cols=4:
    # pos 0: 0+4=4 < 21 (keep), pos 7: 7+4=11 < 21 (keep),
    # pos 14: 14+4=18 < 21 (keep), pos 21: 21+4=25 >= 21 (drop).
    doc.set_point_start().move_point(21)
    doc.insert('x')
    assert len(lay.bol_ladder) == 3


def test_change_handler_drops_entry_at_cols_boundary():
    """An entry exactly `cols` chars before the edit must be truncated."""
    doc = document.Document('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')  # 32 a's
    lay = layout.Layout(doc, 4, 24)  # cols=4
    doc.watch(lay.change_handler)

    # Build ladder entries at positions 0, 4, 8, 12.
    bols = []
    for i in range(4):
        doc.set_point_start().move_point(i * 4)
        bols.append(doc.get_point())
    for b in bols:
        lay.bol_ladder.append(b)

    # Insert at position 8. Pure insertion (exclude_empty=True), remap unchanged.
    # pos 0: 0+4=4 < 8 (keep); pos 4: 4+4=8 >= 8 (drop).
    # Per spec ("more than cols chars before"): only pos 0 survives.
    doc.set_point_start().move_point(8)
    doc.insert('x')
    assert len(lay.bol_ladder) == 1
    assert lay.bol_ladder[0].position() == 0