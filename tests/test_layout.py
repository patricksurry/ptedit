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


def test_ladder_reset():
    lad = Ladder()
    for loc in _locs(3):
        lad.append(loc)
    new_anchor = _locs(1)[0]
    lad.reset(new_anchor)
    assert list(lad) == [new_anchor]


def test_ladder_drops_oldest_past_max():
    """Past MAX entries, the oldest rung is discarded."""
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


def test_locate_cursor():
    doc = document.Document('abcd\nefgh\n')
    lay = layout.Layout(doc, cols=8, rows=4)
    doc.set_point_start()
    lay.ensure_bracketed(doc.get_point())         # seed the ladder from doc start
    doc.move_point(7)                             # 'g': line 1, col 2
    assert lay.locate(doc.get_point()) == (1, 2)


def test_render_lines_formats_and_caches():
    doc = document.Document('aaa\nbbb\nccc\n')
    lay = layout.Layout(doc, cols=8, rows=4)
    lay.reanchor(doc.get_point())
    lines = [bytes(l).rstrip(b'\x00') for l, _ in lay.render_lines(0, 3)]
    assert lines == [b'aaa\n', b'bbb\n', b'ccc\n']
    assert len(lay.bol_ladder) == 3           # anchor + BoLs for rows 1 and 2


def test_make_room_prevents_mid_paint_eviction():
    doc = document.Document('x\n' * 200)
    lay = layout.Layout(doc, cols=16, rows=8)
    lay.reanchor(doc.get_point())
    lay.ensure_row(layout.Ladder.MAX - 1)     # fill the ladder to capacity
    assert len(lay.bol_ladder) == layout.Ladder.MAX
    target = lay.bol_ladder[60]
    top = lay.make_room(60, 8)                # 60 + 8 - 64 = 4 rungs over
    assert top == 56
    assert lay.bol_ladder[top] is target
    assert len(lay.bol_ladder) == layout.Ladder.MAX - 4


def test_change_handler_truncates_at_edit():
    """Ladder entries within cols of the edit are dropped (rule 2: cols-margin)."""
    doc = document.Document('line 1\nline 2\nline 3\nline 4\nline 5\n')
    lay = layout.Layout(doc, 24, 24, 8)
    doc.on_change = lay.note_change

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
    doc.on_change = lay.note_change

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
    doc.on_change = lay.note_change

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

# --- Regression test for the implicit reanchor / bol_to_prev_bol contract ---
#
# `bol_to_prev_bol`'s fallback (cursor at lad[0]) does:
#     move_point(-1) → cursor-1
#     reanchor(cursor-1)
#     if len(bol_ladder) >= 2: set_point(bol_ladder[-2])
#
# This depends on a subtle invariant about reanchor's resulting ladder:
#
#   * In the normal case (cursor-1 is mid-line or at a hard '\n' before
#     non-empty content), reanchor's forward-format loop produces a ladder
#     ending at the position AFTER the '\n' at cursor-1 — i.e., lad[-1] is
#     at position `cursor`, and lad[-2] is the BoL of the line just before
#     cursor. The fallback's `set_point(lad[-2])` then correctly lands at
#     the previous visual BoL.
#
#   * In the empty-line case (doc[cursor-2] == '\n' AND doc[cursor-1] == '\n',
#     i.e., consecutive newlines marking an empty paragraph between two
#     real ones), reanchor's `find_char_backward('\n')` from cursor-1 sees
#     a '\n' immediately behind it and doesn't move — anchor stays at
#     cursor-1, the forward-format loop doesn't run, and the resulting
#     ladder is a single entry [cursor-1]. The fallback's `len >= 2` guard
#     skips the `set_point` and cursor stays at save_pt == cursor-1 — which
#     happens to be the correct answer: the BoL of the empty line.
#
# The "happy accident" in case 2 is what makes deep-reanchor variants (e.g.
# back-scanning past several newlines to produce a bigger initial ladder)
# silently wrong: they make the ladder multi-entry, the `len < 2` guard
# falls through, and `set_point(lad[-2])` lands at the BoL of the line
# BEFORE the empty line, skipping the empty line entirely.
#
# These tests pin the behavior so any future change to reanchor or to the
# fallback has to think about the consecutive-'\n' case explicitly.


def test_bol_to_prev_bol_at_top_lands_on_empty_line():
    """REGRESSION: stepping bol_to_prev_bol from a paragraph whose previous
    visual line is empty (consecutive '\\n's) must land on the empty line,
    not skip over it.

    The fallback path in bol_to_prev_bol (cursor at lad[0], so no cached
    prev BoL) calls `reanchor(cursor-1)`. With shallow reanchor the
    resulting ladder for this case has only one entry, the `len >= 2`
    guard skips `set_point(lad[-2])`, and cursor stays at cursor-1 —
    the empty line's BoL. A deeper reanchor variant would produce a
    multi-entry ladder, the guard would fire, and cursor would land at
    the BoL of the line BEFORE the empty line (wrong).
    """
    # "p1.\n\np3.\n" — 8 chars, with empty paragraph between p1 and p3.
    #  0123 4  56789
    #  p1.  \n \n p3.\n
    # '\n' at position 3 ends paragraph 1.
    # '\n' at position 4 is the empty paragraph (its BoL is also position 4).
    # 'p' at position 5 is the start of paragraph 3 (its hard BoL).
    doc = document.Document('p1.\n\np3.\n')
    lay = layout.Layout(doc, 24, 24)

    # Position cursor at the BoL of paragraph 3 (position 5).
    doc.set_point_start().move_point(5)
    cursor = doc.get_point()

    # Seed the ladder with just [cursor], so cursor is at lad[0] and
    # bol_to_prev_bol falls into the reanchor fallback path.
    lay.bol_ladder.append(cursor)
    assert len(lay.bol_ladder) == 1

    lay.bol_to_prev_bol()

    # Cursor should now be on the empty paragraph (position 4).
    assert doc.get_point().position() == 4, (
        f"bol_to_prev_bol should land on the empty line (pos 4), "
        f"got pos {doc.get_point().position()}"
    )


def test_reanchor_lad_shape_invariant():
    """Document the implicit invariant that bol_to_prev_bol's fallback
    relies on: after `reanchor(cursor)`, EITHER

      (a) the ladder ends with an entry at position `cursor` and a
          previous entry, so set_point(lad[-2]) lands at the prev BoL; OR

      (b) the ladder has exactly one entry at position `cursor`, signalling
          "cursor is itself the BoL we want — don't step further".

    Future changes that produce a multi-entry ladder whose last entry is
    AT position `cursor` (rather than past) would break this contract
    silently — the fallback's `set_point(lad[-2])` would skip the line
    cursor is on. This test catches that.
    """
    # The empty-line case: cursor at position 4 (the '\n' of an empty para).
    # find_char_backward from pos 4 lands at pos 4 (no movement, since
    # doc[3] is already '\n'). Forward-format loop exits immediately.
    # Expected shape: lad = [pos 4]  (single entry).
    doc = document.Document('p1.\n\np3.\n')
    lay = layout.Layout(doc, 24, 24)
    doc.set_point_start().move_point(4)
    cursor = doc.get_point()

    lay.reanchor(cursor)

    if len(lay.bol_ladder) == 1:
        # Shape (b): single-entry ladder; entry IS at cursor's position.
        assert lay.bol_ladder[0].position() == cursor.position()
    else:
        # Shape (a): multi-entry; lad[-1] must be PAST cursor for
        # set_point(lad[-2]) to be the correct prev BoL.
        assert lay.bol_ladder[-1].position() > cursor.position(), (
            f"reanchor invariant violated: lad[-1].pos={lay.bol_ladder[-1].position()} "
            f"should be > cursor.pos={cursor.position()}, or ladder should be "
            f"single-entry. This is the implicit contract bol_to_prev_bol's "
            f"fallback depends on; see docs/rendering.md Open Questions."
        )


def test_bol_to_prev_bol_at_top_of_long_unwrapped_run():
    """A run of non-wrap chars longer than `cols` produces several
    soft-wrap visual lines with NO length-1 lines between them. Stepping
    bol_to_prev_bol off the top of such a region must land exactly one
    visual line back — exercising the reanchor fallback on a soft-wrap
    (not hard) BoL.

    Doc: 'abcdefgh' with cols=4 → visual BoLs 0 ('abcd'), 4 ('efgh').
    bol_to_prev_bol from cursor=4 should land at 0.
    """
    doc = document.Document('abcdefgh')
    lay = layout.Layout(doc, 4, 24)  # cols=4, tab=4

    doc.set_point_start().move_point(4)  # soft-wrap BoL of 'efgh'
    lay.bol_ladder.append(doc.get_point())
    assert len(lay.bol_ladder) == 1

    lay.bol_to_prev_bol()

    assert doc.get_point().position() == 0, (
        f"bol_to_prev_bol from soft-wrap BoL=4 should land at the prior "
        f"visual BoL=0, got pos {doc.get_point().position()}"
    )


def test_bol_to_prev_bol_lands_on_length1_soft_wrap_line():
    """REGRESSION (currently RED — live bug in shallow reanchor).

    `format_line` can emit a length-1 visual line that is NOT an empty
    paragraph: when a line fills exactly `cols` and the next line begins
    with a wrap char followed by enough non-wrap chars to overflow, the
    wrap char gets trimmed onto its own visual line.

    Doc 'abcd efgh', cols=4 (verified via format_line):
        BoL  0: 'abcd'
        BoL  4: ' '        <- length-1 soft-wrap line (the space)
        BoL  5: 'efgh'

    `bol_to_prev_bol` from cursor=5 must land at 4 (the ' ' line).
    It lands at 0 instead — skipping the ' ' line:

      - move_point(-1) -> cursor at 4.
      - reanchor(4): find_char_backward('\\n') finds nothing -> anchor 0.
        format_line at 0 emits 'abcd', point lands at 4. lad=[0, 4].
        Loop `point < cursor_arg(4)` -> 4<4 false -> exit.
        lad[-1] == 4 == cursor_arg  (the bug shape).
      - len(lad) >= 2 -> set_point(lad[-2]=0). Cursor at 0.

    This refutes the earlier claim that shallow reanchor is immune: the
    bug shape requires `cursor_arg` to be a length-1-line BoL, and a
    length-1 line CAN be a soft-wrap artifact (not just an empty
    paragraph). Fix direction: in bol_to_prev_bol's fallback, after
    reanchor, if lad[-1].position() == cursor_arg use lad[-1] directly.
    """
    doc = document.Document('abcd efgh')
    lay = layout.Layout(doc, 4, 24)  # cols=4, tab=4

    doc.set_point_start().move_point(5)  # BoL of 'efgh'
    lay.bol_ladder.append(doc.get_point())
    assert len(lay.bol_ladder) == 1

    lay.bol_to_prev_bol()

    assert doc.get_point().position() == 4, (
        f"bol_to_prev_bol from BoL=5 should land on the ' ' line at "
        f"pos 4, got pos {doc.get_point().position()}"
    )


def test_goal_column_persists_across_short_line():
    """Vertical moves land on the goal column immediately (no paint needed)."""
    doc = document.Document('abcdefgh\nab\nabcdefgh\n')
    lay = layout.Layout(doc, cols=16, rows=8)
    doc.move_point(5)                           # line 0, col 5
    lay.move_forward_line()
    assert doc.get_point().position() == 11     # 'ab' line clamps to its newline (col 2)
    lay.move_forward_line()
    assert doc.get_point().position() == 17     # long line again: goal col 5 restored


def test_vertical_move_at_start_clamps_to_bol():
    doc = document.Document('abcdefgh\nab\n')
    lay = layout.Layout(doc, cols=16, rows=8)
    doc.move_point(5)
    lay.move_backward_line()                    # no line above: clamp to BoL
    assert doc.get_point().position() == 0


def test_vertical_move_from_doc_end_without_trailing_newline():
    """Parity guard: a cursor at doc end targets col 0 for the *next* vertical
    move — but here that next move is the one moving off doc end, and it lands
    on the BoL of the line doc end sits on (position 9, 'abcd'), not line 0.

    Verified against the true old renderer (Layout-only AND the full
    Display.paint pipeline): `ensure_bracketed` treats a cursor exactly at doc
    end (no trailing newline) as bracketed by the ladder's trailing phantom
    entry — itself equal to doc end — so a single bol_to_prev_bol from there
    steps back only to the real last line's BoL, not past it. This matches
    old-renderer behavior byte-for-byte; it is not a regression.
    """
    doc = document.Document('abcdefgh\nabcd')
    lay = layout.Layout(doc, cols=16, rows=8)
    doc.set_point_end()                         # EOD marker at col 4 of line 1
    lay.move_backward_line()
    assert doc.get_point().position() == 9      # BoL of 'abcd' (line 1, col 0)
