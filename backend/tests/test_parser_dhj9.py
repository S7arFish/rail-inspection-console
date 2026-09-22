"""Test 1 + parser-level guards for the real DHJ-9 record shape."""

from __future__ import annotations

from app.parser.line_parser import KIND_CONTROL, KIND_DATA, KIND_HEADER, KIND_INVALID

REAL_LINE = "0,0,0,0,0,1,1,260922-091952,2121.5,582.2,1434.6,-9.8"
HEADER_LINE = "记录类型,测量方向,记录号,线号,工区,杆号,测量位置,时间,高度,拉出,轨距"


def test_real_record_maps_to_confirmed_field_names(parser):
    """The 12 columns land under the instrument's own names."""
    parsed = parser.parse(REAL_LINE)

    assert parsed.kind == KIND_DATA
    fields = parsed.fields

    assert fields["record_type"] == 0
    assert fields["measure_direction"] == 0
    assert fields["record_no"] == 0
    assert fields["line_no"] == 0
    assert fields["work_area"] == 0
    assert fields["pole_no"] == 1
    assert fields["measure_position"] == 1
    assert fields["height"] == 2121.5
    assert fields["pull_out"] == 582.2
    assert fields["gauge"] == 1434.6
    assert fields["metric_extra_1"] == -9.8


def test_timestamp_kept_raw_and_normalised(parser):
    """`260922-091952` = 2026-09-22 09:19:52, and the raw text is preserved."""
    parsed = parser.parse(REAL_LINE)

    assert parsed.ts_raw == "260922-091952"
    assert parsed.ts == "2026-09-22T09:19:52"
    assert parsed.timestamp_error is False
    # the timestamp has dedicated columns, so it is not duplicated in `fields`
    assert "timestamp" not in parsed.fields


def test_bad_timestamp_never_drops_the_row(parser):
    parsed = parser.parse("0,0,0,0,0,1,1,not-a-date,2121.5,582.2,1434.6,-9.8")

    assert parsed.kind == KIND_DATA
    assert parsed.ts_raw == "not-a-date"
    assert parsed.ts is None
    assert parsed.fields["height"] == 2121.5


def test_metric_extra_1_stays_neutral(config):
    """Position 11 has no header counterpart: neutral name, unconfirmed."""
    extra = next(spec for spec in config.fields if spec.index == 11)

    assert extra.name == "metric_extra_1"
    assert extra.confirmed is False
    assert extra.unit is None


def test_header_positions_0_to_10_are_confirmed(config):
    confirmed = {spec.index: spec.confirmed for spec in config.fields}

    assert all(confirmed[index] for index in range(11))
    assert confirmed[11] is False


def test_instrument_header_is_protocol(parser):
    assert parser.parse(HEADER_LINE).kind == KIND_HEADER
    assert parser.classify(HEADER_LINE) == KIND_HEADER


def test_over_terminates_the_batch(parser):
    parsed = parser.parse("OVER")

    assert parsed.kind == KIND_CONTROL
    assert parsed.is_control


def test_sscom_display_prefix_is_not_part_of_the_protocol(parser):
    """SSCOM draws `[16:41:05.296]收←◆` itself; a real record must not need it,
    and a line carrying it is simply not a valid record."""
    assert parser.parse(REAL_LINE).kind == KIND_DATA
    assert parser.parse(f"[16:41:05.296]收←◆{REAL_LINE}").kind == KIND_INVALID


def test_short_line_is_invalid_not_fatal(parser):
    parsed = parser.parse("abc,123")

    assert parsed.kind == KIND_INVALID
    assert parsed.parse_error
