"""Cross-platform serial tests: CP2102 detection on Linux and Windows, plus the
GBK/GB18030 header the real DHJ-9 sends.

The Pi case is why this file exists: on a UTF-8 terminal the header looks like
mojibake, so a decoder that guesses UTF-8 hands the parser garbage and the batch
never opens. These tests pin the bytes -> text -> KIND_HEADER -> database path.
"""

from __future__ import annotations

import logging

import pytest
from app.db import repository
from app.parser.line_parser import KIND_CONTROL, KIND_DATA, KIND_HEADER, KIND_INVALID
from app.services.realtime import EventBridge
from app.services.serial_service import LinkConfig
from app.services.serial_service import SerialService
from app.text_decoder import decode_serial_line
from tests.conftest import FakeSerial, INSTRUMENT_HEADER

DATA_LINE = "0,0,0,0,0,1,1,260922-091952,2121.5,582.2,1434.6,-9.8"
DHJ9_VID = 0x10C4
DHJ9_PID = 0xEA60


class FakePort:
    """Stands in for one `serial.tools.list_ports` entry."""

    def __init__(self, *, device, name=None, description="", hwid="", manufacturer="",
                 vid=None, pid=None, serial_number=""):
        self.device = device
        self.name = name or device
        self.description = description
        self.hwid = hwid
        self.manufacturer = manufacturer
        self.vid = vid
        self.pid = pid
        self.serial_number = serial_number


def linux_dhj9():
    return FakePort(
        device="/dev/ttyUSB0", name="ttyUSB0",
        description="CP2102 USB to UART Bridge Controller",
        hwid="USB VID:PID=10C4:EA60 SER=0001",
        manufacturer="Silicon Labs", vid=DHJ9_VID, pid=DHJ9_PID, serial_number="0001",
    )


def other_usb_uart(device="/dev/ttyUSB1"):
    return FakePort(
        device=device, name=device.rsplit("/", 1)[-1], description="USB Serial Port",
        hwid="USB VID:PID=1A86:7523", manufacturer="wch.cn", vid=0x1A86, pid=0x7523,
    )


def windows_com7():
    return FakePort(
        device="COM7", name="COM7",
        description="Silicon Labs CP210x USB to UART Bridge (COM7)",
        hwid="USB VID:PID=10C4:EA60 SER=0001",
        manufacturer="Silicon Labs", vid=DHJ9_VID, pid=DHJ9_PID, serial_number="0001",
    )


@pytest.fixture()
def wire(db, parser, app_settings):
    """A service on a fake port plus the envelopes it pushed."""
    captured: list[dict] = []

    def publisher(envelope):
        captured.append(envelope)
        return 1

    service = SerialService(
        settings=app_settings,
        database=db,
        parser=parser,
        bridge=EventBridge(publisher=publisher),
        serial_factory=lambda **kwargs: FakeSerial(**kwargs),
        port_lister=lambda: [other_usb_uart(), linux_dhj9()],
    )
    yield service, captured
    service.stop()


# ---------------------------------------------------------------- decoding
def test_gbk_header_bytes_decode_back_to_chinese():
    """Test A: the device's GB18030 header must become real Chinese text."""
    decoded = decode_serial_line(INSTRUMENT_HEADER.encode("gb18030"))

    assert decoded.text == INSTRUMENT_HEADER
    assert decoded.encoding == "gb18030"
    assert decoded.had_decode_error is False


def test_utf8_header_bytes_also_decode(parser):
    """Test B: a UTF-8 header is equally fine, and both reach KIND_HEADER."""
    for encoding in ("utf-8", "gb18030"):
        decoded = decode_serial_line(INSTRUMENT_HEADER.encode(encoding))
        assert decoded.text == INSTRUMENT_HEADER
        assert decoded.encoding == encoding
        assert decoded.had_decode_error is False
        assert parser.classify(decoded.text) == KIND_HEADER


def test_ascii_line_is_reported_as_ascii():
    decoded = decode_serial_line(DATA_LINE.encode("ascii") + b"\r\n")

    assert decoded.is_ascii is True
    assert decoded.had_decode_error is False


def test_undecodable_bytes_never_raise():
    """Test H: garbage degrades to a replacement string, no exception."""
    decoded = decode_serial_line(bytes([0xFF, 0xFE, 0x00, 0xC0, 0x80, 0x41]))

    assert decoded.had_decode_error is True
    assert "replace" in decoded.encoding
    assert isinstance(decoded.text, str)


# ------------------------------------------------------- parse after decode
def test_ascii_data_line_parses(parser):
    """Test C: CRLF-terminated wire line -> all four metrics."""
    parsed = parser.parse(decode_serial_line(DATA_LINE.encode() + b"\r\n").text)

    assert parsed.kind == KIND_DATA
    assert parsed.fields["height"] == 2121.5
    assert parsed.fields["pull_out"] == 582.2
    assert parsed.fields["gauge"] == 1434.6
    assert parsed.fields["metric_extra_1"] == -9.8


def test_over_with_any_line_ending_is_the_terminator(parser):
    """Test D: OVER, OVER\\r, OVER\\n and OVER\\r\\n all close the batch."""
    for ending in (b"", b"\r", b"\n", b"\r\n"):
        parsed = parser.parse(decode_serial_line(b"OVER" + ending).text)
        assert parsed.kind == KIND_CONTROL, ending


def test_garbage_line_is_invalid_not_fatal(parser):
    decoded = decode_serial_line(bytes([0xFF, 0xFE, 0xFF]))

    assert parser.parse(decoded.text).kind == KIND_INVALID


# -------------------------------------------------------------- port lists
def test_linux_cp2102_is_suggested(db, parser, bridge, app_settings):
    """Test E: /dev/ttyUSB0 with the DHJ-9's VID/PID wins on Linux."""
    service = SerialService(
        settings=app_settings, database=db, parser=parser, bridge=bridge,
        serial_factory=lambda **kw: FakeSerial(**kw),
        port_lister=lambda: [other_usb_uart(), linux_dhj9()],
    )

    view = service.enumerate_ports()

    assert view.ports[0].device == "/dev/ttyUSB0"
    assert view.ports[0].suggested is True
    assert view.ports[0].vid == DHJ9_VID
    assert view.ports[0].pid == DHJ9_PID
    assert view.ports[0].serial_number == "0001"
    assert view.ports[0].manufacturer == "Silicon Labs"
    assert view.suggested_port == "/dev/ttyUSB0"


def test_other_usb_uart_is_not_suggested(db, parser, bridge, app_settings):
    """Test F: a different VID/PID with a generic description is not the DHJ-9."""
    service = SerialService(
        settings=app_settings, database=db, parser=parser, bridge=bridge,
        serial_factory=lambda **kw: FakeSerial(**kw),
        port_lister=lambda: [other_usb_uart()],
    )

    view = service.enumerate_ports()

    assert view.ports[0].suggested is False
    # still usable: with no CP2102 present the console falls back to what exists
    assert view.suggested_port == "/dev/ttyUSB1"


def test_windows_com_port_still_suggested(db, parser, bridge, app_settings):
    """Test G: the pre-existing Windows behaviour must not regress."""
    service = SerialService(
        settings=app_settings, database=db, parser=parser, bridge=bridge,
        serial_factory=lambda **kw: FakeSerial(**kw),
        port_lister=lambda: [
            FakePort(device="COM3", description="Intel(R) Active Management Technology - SOL (COM3)",
                     hwid="ACPI\\INTC0E9", manufacturer="Intel"),
            windows_com7(),
        ],
    )

    view = service.enumerate_ports()

    assert view.ports[0].device == "COM7"
    assert view.ports[0].suggested is True
    assert view.suggested_port == "COM7"


def test_windows_detection_survives_missing_usb_ids(db, parser, bridge, app_settings):
    """Some Windows drivers report no vid/pid: the text markers must still work."""
    service = SerialService(
        settings=app_settings, database=db, parser=parser, bridge=bridge,
        serial_factory=lambda **kw: FakeSerial(**kw),
        port_lister=lambda: [
            FakePort(device="COM7", description="Silicon Labs CP210x USB to UART Bridge (COM7)"),
        ],
    )

    assert service.enumerate_ports().suggested_port == "COM7"


def test_connect_accepts_a_linux_device_path(wire):
    """A /dev/ path must flow through connect and status untouched."""
    service, _envelopes = wire

    result = service.connect()

    assert result.ok is True
    assert result.port == "/dev/ttyUSB0"  # auto-selected, no COM assumption
    assert service.status()["port"] == "/dev/ttyUSB0"
    assert service.status()["state"] == "connected_waiting"


def test_flow_control_is_explicitly_off_for_the_dhj9_cable():
    """115200 8N1 with no handshake: the flags are stated, not defaulted.

    A stray RTS/CTS on a Linux cp210x port stalls reads silently, which is
    exactly the kind of failure that ends up blamed on the instrument.
    """
    kwargs = LinkConfig(
        port="/dev/ttyUSB0", baud_rate=115200, data_bits=8, parity="N",
        stop_bits=1, flow_control="none",
    ).serial_kwargs()

    assert kwargs["rtscts"] is False
    assert kwargs["xonxoff"] is False
    assert kwargs["bytesize"] == 8
    assert kwargs["parity"] == "N"
    assert kwargs["stopbits"] == 1
    assert kwargs["port"] == "/dev/ttyUSB0"


# ------------------------------------- the whole Pi path, bytes to database
def test_gbk_header_over_the_wire_opens_the_batch(wire, db):
    """The real Pi sequence end to end: GB18030 header bytes, then records."""
    service, envelopes = wire
    assert service.connect().ok

    service.handle_raw_chunk(INSTRUMENT_HEADER.encode("gb18030") + b"\r\n")
    assert service.status()["state"] == "receiving"

    for line in (DATA_LINE, "OVER"):
        service.handle_raw_chunk(line.encode("ascii") + b"\r\n")

    session = repository.list_sessions(db, limit=10)[0][0]
    assert session["status"] == repository.STATUS_COMPLETED
    assert session["sample_count"] == 1

    archived = [row["line"] for row in repository.list_raw_lines(db, session["id"])[0]]
    assert INSTRUMENT_HEADER in archived  # readable Chinese, not replacement chars
    assert any(e["type"] == "session.complete" for e in envelopes)
    # OVER ended the batch, not the connection
    assert service.status()["state"] == "connected_waiting"


def test_detected_encoding_is_logged_once(connected, caplog):
    """A non-ASCII line is reported once; ASCII lines stay silent."""
    with caplog.at_level(logging.INFO, logger="app.services.serial_service"):
        for _ in range(3):
            connected.handle_raw_chunk(INSTRUMENT_HEADER.encode("gb18030") + b"\r\n")
        for line in (DATA_LINE, "OVER"):
            connected.handle_raw_chunk(line.encode() + b"\r\n")

    detected = [r for r in caplog.records if "encoding detected" in r.getMessage()]
    assert len(detected) == 1
    assert "gb18030" in detected[0].getMessage()
