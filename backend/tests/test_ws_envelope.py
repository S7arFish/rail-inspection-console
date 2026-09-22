"""Test 5: the /ws/live envelope contract, and the DHJ-9 source tag.

Every frame must be ``{ type, source, timestamp, payload }`` so a second data
source (a future vision rig) can share this socket without ambiguity.
"""

from __future__ import annotations

from app.services.realtime import SOURCE_CONSOLE, SOURCE_DHG9
from tests.conftest import REAL_BATCH

ENVELOPE_KEYS = {"type", "source", "timestamp", "payload"}


def _types(envelopes):
    return [envelope["type"] for envelope in envelopes]


def test_measurement_event_shape(connected, envelopes):
    """The core requirement: a measurement frame is complete and tagged dhj9."""
    envelopes.clear()
    connected.ingest_line(REAL_BATCH[0])

    frames = [e for e in envelopes if e["type"] == "laser.measurement"]
    assert len(frames) == 1
    frame = frames[0]

    assert set(frame) == ENVELOPE_KEYS
    assert frame["source"] == SOURCE_DHG9 == "dhj9"
    assert frame["timestamp"]
    assert frame["payload"]["fields"]["metric_extra_1"] == -9.8
    assert frame["payload"]["ts_raw"] == "260922-091952"
    assert frame["payload"]["raw_line"] == REAL_BATCH[0]
    assert frame["payload"]["session_id"] == connected.session_id


def test_session_complete_event(connected, envelopes):
    envelopes.clear()
    for line in REAL_BATCH:
        connected.ingest_line(line)

    frames = [e for e in envelopes if e["type"] == "session.complete"]
    assert len(frames) == 1
    frame = frames[0]

    assert set(frame) == ENVELOPE_KEYS
    assert frame["source"] == "dhj9"
    payload = frame["payload"]
    assert payload["record_count"] == 6
    assert payload["status"] == "completed"
    assert payload["session_id"]
    assert payload["ended_at"]


def test_status_events_track_the_batch_state(connected, envelopes):
    envelopes.clear()
    connected.ingest_line(REAL_BATCH[0])
    connected.ingest_line("OVER")

    statuses = [e for e in envelopes if e["type"] == "laser.status"]
    assert [s["payload"]["state"] for s in statuses] == ["receiving", "connected_waiting"]
    assert all(s["source"] == "dhj9" for s in statuses)
    assert statuses[0]["payload"]["records_in_batch"] == 1


def test_parse_error_event(connected, envelopes):
    envelopes.clear()
    connected.ingest_line(REAL_BATCH[0])  # open a batch first
    connected.ingest_line("abc,123")

    frames = [e for e in envelopes if e["type"] == "laser.parse_error"]
    assert len(frames) == 1
    assert set(frames[0]) == ENVELOPE_KEYS
    assert frames[0]["source"] == "dhj9"
    assert frames[0]["payload"]["line"] == "abc,123"


def test_every_frame_from_one_export_carries_the_source(connected, envelopes):
    envelopes.clear()
    for line in REAL_BATCH:
        connected.ingest_line(line)

    assert envelopes, "the batch produced no events at all"
    assert all(set(e) == ENVELOPE_KEYS for e in envelopes)
    assert all(e["source"] in (SOURCE_DHG9, SOURCE_CONSOLE) for e in envelopes)
    assert all(e["source"] == SOURCE_DHG9 for e in envelopes)
    assert set(_types(envelopes)) <= {
        "laser.measurement",
        "laser.status",
        "laser.parse_error",
        "session.complete",
    }
