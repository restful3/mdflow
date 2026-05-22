from mdflow.converters._md_table import escape_table_cell


def test_escapes_pipe():
    assert escape_table_cell("a|b") == "a\\|b"


def test_flattens_newlines_to_space():
    assert escape_table_cell("line1\nline2") == "line1 line2"
    assert escape_table_cell("a\r\nb\rc") == "a b c"


def test_plain_text_unchanged():
    assert escape_table_cell("plain") == "plain"
    assert escape_table_cell("") == ""
