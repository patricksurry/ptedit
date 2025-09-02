from ptedit import formatter, piecetable


def test_wrap():
    doc = piecetable.Document('the big\t 012345678901234567890123456789 number')
    fmt = formatter.Formatter(doc, 24, 8)

    assert doc.at_start()
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9
    fmt.bol_to_next_bol()
    assert doc.get_point().position() == 9 + 24
    fmt.bol_to_next_bol()
    assert doc.at_end()
