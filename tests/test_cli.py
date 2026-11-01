import io

from parity_cli import cli


def test_output_survives_a_non_utf8_console():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    cli._use_utf8_output(stream)
    stream.write("\u2713")
    stream.flush()
    assert raw.getvalue() == "\u2713".encode("utf-8")
