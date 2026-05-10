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
    assert lad.first == 0
    assert lad.last == 0


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
    fmt = layout.Layout(doc, 24, 24, 8)

    assert doc.at_start()
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9 + 24
    fmt.bol_to_next_bol()
    assert doc.at_end(), f"{doc.get_point().position()}/{len(doc)}"


def test_format():
    doc = document.Document('the \tbig\t 012345678901234567890123456789\r\x01 number\x7f')
    fmt = layout.Layout(doc, 24, 24, 8)
    assert fmt.format_line()[0] == b'the \t\0\0\0big\t ' + bytes(11)
    assert fmt.format_line()[0] == b'012345678901234567890123'
    assert fmt.format_line()[0] == b'456789\x01M\x01A number\x027F' + bytes(4)


def test_column_for_offset():
    doc = document.Document('456789\r\x01 number\x7f')
    fmt = layout.Layout(doc, 24, 24, 8)
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
    fmt = layout.Layout(doc, 24, 24, 8)
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
    """Ladder entries near or after the edit are dropped."""
    doc = document.Document('line 1\nline 2\nline 3\nline 4\nline 5\n')
    lay = layout.Layout(doc, 24, 24, 8)

    # Manually populate the ladder by appending BoL marks at known positions.
    # (Phase 1 will populate this organically in Task 2.3; for this unit test
    # we seed it directly.)
    doc.set_point_start()
    bol1 = doc.get_point()
    doc.move_point(7)  # past 'line 1\n'
    bol2 = doc.get_point()
    doc.move_point(7)  # past 'line 2\n'
    bol3 = doc.get_point()
    doc.move_point(7)
    bol4 = doc.get_point()
    for b in (bol1, bol2, bol3, bol4):
        lay.bol_ladder.append(b)
    assert len(lay.bol_ladder) == 4

    # Simulate an edit at position 14 (start of 'line 3').
    doc.set_point_start().move_point(14)
    lay.change_handler(doc.get_point(), doc.get_point(), unlinked=set())

    # With cols=24 and edit_pos=14, every entry with position + 24 > 14 is
    # dropped. bol1 is at pos 0: 0 + 24 = 24 > 14, so it's dropped too.
    # All 4 entries are dropped.
    assert len(lay.bol_ladder) == 0


def test_change_handler_keeps_far_entries():
    """Ladder entries more than `cols` chars before edit survive."""
    doc = document.Document('line 1\nline 2\nline 3\nline 4\nline 5\n')
    lay = layout.Layout(doc, 4, 24, 8)  # cols=4

    doc.set_point_start()
    bols = []
    for _ in range(4):
        bols.append(doc.get_point())
        doc.move_point(7)

    for b in bols:
        lay.bol_ladder.append(b)

    # Edit at position 21 (start of 'line 4'). With cols=4, entries with
    # position + 4 <= 21 survive. bol1=pos 0 (0+4=4 <= 21 OK),
    # bol2=pos 7 (7+4=11 <= 21 OK), bol3=pos 14 (14+4=18 <= 21 OK),
    # bol4=pos 21 (21+4=25 > 21, dropped).
    doc.set_point_start().move_point(21)
    lay.change_handler(doc.get_point(), doc.get_point(), unlinked=set())

    assert len(lay.bol_ladder) == 3