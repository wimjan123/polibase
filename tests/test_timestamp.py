from factbase.utils import parse_timestamp_range


def test_parse_range():
    s, e, d = parse_timestamp_range("00:00:00-00:00:26 (27 sec)")
    assert s == 0
    assert e == 26
    assert d == 27


def test_parse_single():
    s, e, d = parse_timestamp_range("01:02:03")
    assert s == 3723
    assert e is None
    assert d is None


def test_parse_edge():
    s, e, d = parse_timestamp_range("99:59:59-100:00:00 (1 sec)")
    assert s == 359999
    assert e == 360000
    assert d == 1

