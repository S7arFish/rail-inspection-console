"""Tests 2-4: the batch state machine over a fake port.

One 导出记录 = one session. ``OVER`` closes the session and returns the link to
``connected_waiting`` while the port stays open.
"""

from __future__ import annotations

from app.db import repository
from app.services.serial_service import SerialState
from tests.conftest import INSTRUMENT_HEADER, REAL_BATCH

RECORDS = REAL_BATCH[:-1]  # the six data lines, without the terminator


def _sessions(service):
    items, _total = repository.list_sessions(service.db, limit=100)
    return items


def test_connect_does_not_open_a_session(connected):
    """Waiting for an export is not a batch: no session row yet."""
    assert connected.state is SerialState.CONNECTED_WAITING
    assert connected.session_id is None
    assert _sessions(connected) == []


def test_one_batch_makes_one_completed_session(connected, db):
    """Test 2: six records + OVER -> one session, six records, completed."""
    for line in REAL_BATCH:
        connected.ingest_line(line)

    sessions = _sessions(connected)
    assert len(sessions) == 1
    session = sessions[0]

    assert session["status"] == repository.STATUS_COMPLETED
    assert session["ended_at"] is not None
    assert session["sample_count"] == 6
    assert repository.count_measurements(db, session["id"]) == 6
    # every physical line of the batch is archived, the terminator included
    assert repository.count_raw_lines(db, session["id"]) == 7


def test_link_waits_for_the_next_export_after_over(connected):
    """OVER ends the batch, never the connection."""
    for line in REAL_BATCH:
        connected.ingest_line(line)

    assert connected.state is SerialState.CONNECTED_WAITING
    assert connected.is_connected() is True
    assert connected.session_id is None
    assert connected.status()["records_in_batch"] == 0


def test_status_reports_receiving_progress(connected):
    connected.ingest_line(RECORDS[0])
    connected.ingest_line(RECORDS[1])

    status = connected.status()
    assert connected.state is SerialState.RECEIVING
    assert status["state"] == "receiving"
    assert status["records_in_batch"] == 2
    assert status["session_id"] is not None

    connected.ingest_line("OVER")
    assert connected.status()["records_in_batch"] == 0


def test_second_export_creates_a_second_session(connected, db):
    """Test 3: a new batch must not be written into the first session."""
    for line in REAL_BATCH:
        connected.ingest_line(line)
    first_id = _sessions(connected)[0]["id"]

    for line in [RECORDS[0], "OVER"]:
        connected.ingest_line(line)

    sessions = _sessions(connected)
    assert len(sessions) == 2
    second_id = next(s["id"] for s in sessions if s["id"] != first_id)

    assert repository.count_measurements(db, first_id) == 6
    assert repository.count_measurements(db, second_id) == 1
    assert repository.get_session(db, second_id)["status"] == repository.STATUS_COMPLETED


def test_header_line_starts_the_session(connected):
    """An export that echoes the instrument header opens the batch with it."""
    connected.ingest_line(INSTRUMENT_HEADER)

    assert connected.state is SerialState.RECEIVING
    session_id = connected.session_id
    assert session_id is not None

    connected.ingest_line(RECORDS[0])
    connected.ingest_line("OVER")

    session = _sessions(connected)[0]
    assert session["id"] == session_id
    assert session["sample_count"] == 1
    # header + record + terminator, all archived
    assert repository.count_raw_lines(connected.db, session["id"]) == 3


def test_garbage_lines_are_survived(connected, db):
    """Test 4: malformed, blank and unknown text must not break the reader."""
    connected.ingest_line(RECORDS[0])  # open a batch so lines can be archived

    for junk in ["abc,123", "", "   ", "未知中文文本", "0,0,0"]:
        connected.ingest_line(junk)

    assert connected.state is SerialState.RECEIVING
    assert connected.status()["parse_error_count"] >= 4

    connected.ingest_line("OVER")

    session = _sessions(connected)[0]
    assert session["sample_count"] == 1
    kinds = {row["kind"] for row in repository.list_raw_lines(db, session["id"])[0]}
    assert "invalid" in kinds and "data" in kinds and "control" in kinds
    # the good record survived alongside the garbage
    assert repository.count_measurements(db, session["id"]) == 1


def test_junk_before_any_record_is_ignored_safely(connected, db):
    """raw_lines.session_id is a NOT NULL FK, so a line that arrives before the
    first record of a batch is counted and reported, not archived."""
    connected.ingest_line("abc,123")
    connected.ingest_line("")

    assert connected.state is SerialState.CONNECTED_WAITING
    assert connected.session_id is None
    assert _sessions(connected) == []
    # both lines are counted as failures; neither can be archived without a session
    assert connected.status()["parse_error_count"] == 2


def test_over_without_a_batch_is_ignored(connected, db):
    """A stray terminator on an idle link must not invent an empty session."""
    connected.ingest_line("OVER")

    assert connected.state is SerialState.CONNECTED_WAITING
    assert _sessions(connected) == []


def test_disconnect_finalizes_an_open_batch_as_interrupted(connected, db):
    """Pulling the plug mid-export must not lose the rows already received."""
    for line in RECORDS[:3]:
        connected.ingest_line(line)

    session_id = connected.session_id
    result = connected.disconnect(reason="operator stopped")

    assert result.ok is True
    assert connected.state is SerialState.DISCONNECTED
    assert repository.get_session(db, session_id)["status"] == repository.STATUS_INTERRUPTED
    assert repository.count_measurements(db, session_id) == 3


def test_reader_thread_is_not_duplicated(connected):
    """A second connect while the link is up is rejected, not threaded."""
    before = connected.status()
    second = connected.connect()

    assert second.ok is False
    assert connected.status()["state"] == before["state"]


def test_port_held_by_another_program_reports_in_chinese(db, parser, bridge, app_settings):
    """SSCOM (or anything else) keeping the COM port open is the common real-world
    failure: it must come back as a readable Chinese message, never a traceback."""
    from app.services.serial_service import SerialService, SerialState

    def busy_factory(**kwargs):
        raise PermissionError(13, "拒绝访问。", kwargs.get("port"), 5, "Access is denied")

    service = SerialService(
        settings=app_settings,
        database=db,
        parser=parser,
        bridge=bridge,
        serial_factory=busy_factory,
        port_lister=lambda: [],
    )
    result = service.connect()

    assert result.ok is False
    assert service.state is SerialState.ERROR
    assert "占用" in result.message
    assert "SSCOM" in result.message
    # a failed link never reports a live port
    assert service.status()["port"] is None


def test_missing_port_reports_in_chinese(db, parser, bridge, app_settings):
    from app.services.serial_service import SerialService

    def missing_factory(**kwargs):
        raise FileNotFoundError(2, "系统找不到指定的文件。")

    service = SerialService(
        settings=app_settings,
        database=db,
        parser=parser,
        bridge=bridge,
        serial_factory=missing_factory,
        port_lister=lambda: [],
    )
    result = service.connect()

    assert result.ok is False
    assert "不存在" in result.message
