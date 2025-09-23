from ptedit import document, formatter


def test_bol():
    doc = document.Document('the big\t 012345678901234567890123456789 number')
    fmt = formatter.Formatter(doc, 24, 8)

    assert doc.at_start()
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9 + 24
    fmt.bol_to_next_bol()
    assert doc.at_end(), f"{doc.get_point().position()}/{len(doc)}"


def test_format():
    doc = document.Document('the \tbig\t 012345678901234567890123456789\r\x01 number\x7f')
    fmt = formatter.Formatter(doc, 24, 8)
    assert fmt.format_line()[0] == b'the \t\0\0\0big\t ' + bytes(11)
    assert fmt.format_line()[0] == b'012345678901234567890123'
    assert fmt.format_line()[0] == b'456789\x01M\x01A number\x027F' + bytes(4)


def test_column_for_offset():
    doc = document.Document('456789\r\x01 number\x7f')
    fmt = formatter.Formatter(doc, 24, 8)
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
    fmt = formatter.Formatter(doc, 24, 8)
    line, col_map = fmt.format_line()
    assert line == b'456789\x01M\x01A' + bytes(14)
    assert formatter.Formatter.offset_for_column(0, col_map) == 0
    assert formatter.Formatter.offset_for_column(5, col_map) == 5
    assert formatter.Formatter.offset_for_column(6, col_map) == 6  # ^
    assert formatter.Formatter.offset_for_column(7, col_map) == 6  # M
    assert formatter.Formatter.offset_for_column(8, col_map) == 7  # ^
    assert formatter.Formatter.offset_for_column(9, col_map) == 7  # A
    assert formatter.Formatter.offset_for_column(10, col_map) == 8  # eod
    assert formatter.Formatter.offset_for_column(99, col_map) == 8  # eod