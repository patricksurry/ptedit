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
    assert doc.at_end()


def test_format():
    doc = document.Document('the \tbig\t 012345678901234567890123456789\r\x01 number\x7f')
    fmt = formatter.Formatter(doc, 24, 8)
    assert fmt.format_line() == b'the \t\0\0\0big\t ' + bytes(11)
    assert fmt.format_line() == b'012345678901234567890123'
    assert fmt.format_line() == b'456789\x01M\x01A number\x027F' + bytes(4)


def test_column_for_offset():
    line = b'456789\x01M\x01A number\x027F' + bytes(4)
    assert formatter.Formatter.column_for_offset(0, line) == 0
    assert formatter.Formatter.column_for_offset(6, line) == 6
    assert formatter.Formatter.column_for_offset(7, line) == 8
    assert formatter.Formatter.column_for_offset(15, line) == 17
    assert formatter.Formatter.column_for_offset(16, line) == 20

    assert formatter.Formatter.column_for_offset(5, b'abcd') == 3

def test_offset_for_column():
    line = b'456789\x01M\x01A' + bytes(4)
    assert formatter.Formatter.offset_for_column(0, line) == 0
    assert formatter.Formatter.offset_for_column(5, line) == 5
    assert formatter.Formatter.offset_for_column(6, line) == 6  # ^
    assert formatter.Formatter.offset_for_column(7, line) == 6  # M
    assert formatter.Formatter.offset_for_column(8, line) == 7  # ^
    assert formatter.Formatter.offset_for_column(9, line) == 7  # A
    assert formatter.Formatter.offset_for_column(10, line) == 7  # 0