from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

import pytest

from marketwatch.core.events import Event, EventValidationError, VALID_EVENT_TYPES
from marketwatch.storage.ledger import append_events, read_events, LedgerParseError


def test_event_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    event = Event(
        id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().replace(microsecond=0),
        type="cash_movement",
        payload={"amount": 123.45},
        note="test",
    )
    append_events(path, [event])

    events = list(read_events(path))
    assert len(events) == 1
    loaded = events[0]
    assert loaded.id == event.id
    assert loaded.type == event.type
    assert loaded.payload["amount"] == event.payload["amount"]
    assert loaded.note == event.note


def test_read_events_skips_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON lines should be skipped in non-strict mode."""
    path = tmp_path / "ledger.jsonl"

    # Write valid event, malformed line, then another valid event
    valid_event = {
        "id": "valid-1",
        "timestamp": "2025-01-01T00:00:00",
        "type": "cash_movement",
        "payload": {"amount": 100.0},
    }
    path.write_text(
        '{"id":"valid-1","timestamp":"2025-01-01T00:00:00","type":"cash_movement","payload":{"amount":100}}\n'
        '{this is not valid json}\n'
        '{"id":"valid-2","timestamp":"2025-01-02T00:00:00","type":"cash_movement","payload":{"amount":200}}\n'
    )

    events = list(read_events(path))
    assert len(events) == 2
    assert events[0].id == "valid-1"
    assert events[1].id == "valid-2"


def test_read_events_strict_mode_raises_on_malformed_json(tmp_path: Path) -> None:
    """In strict mode, malformed JSON should raise LedgerParseError."""
    path = tmp_path / "ledger.jsonl"
    path.write_text('{not valid json}\n')

    with pytest.raises(LedgerParseError) as exc_info:
        list(read_events(path, strict=True))

    assert "Malformed JSON at line 1" in str(exc_info.value)


def test_read_events_skips_invalid_event_data(tmp_path: Path) -> None:
    """Events with missing required fields should be skipped in non-strict mode."""
    path = tmp_path / "ledger.jsonl"

    # Valid JSON but missing required 'timestamp' field
    path.write_text(
        '{"id":"valid-1","timestamp":"2025-01-01T00:00:00","type":"cash_movement","payload":{"amount":100}}\n'
        '{"id":"missing-timestamp","type":"cash_movement","payload":{}}\n'
        '{"id":"valid-2","timestamp":"2025-01-02T00:00:00","type":"cash_movement","payload":{"amount":200}}\n'
    )

    events = list(read_events(path))
    assert len(events) == 2
    assert events[0].id == "valid-1"
    assert events[1].id == "valid-2"


def test_read_events_strict_mode_raises_on_invalid_event(tmp_path: Path) -> None:
    """In strict mode, missing required fields should raise LedgerParseError."""
    path = tmp_path / "ledger.jsonl"
    # Valid JSON but missing 'timestamp'
    path.write_text('{"id":"test","type":"cash_movement","payload":{}}\n')

    with pytest.raises(LedgerParseError) as exc_info:
        list(read_events(path, strict=True))

    assert "Invalid event data at line 1" in str(exc_info.value)


def test_read_events_empty_lines_skipped(tmp_path: Path) -> None:
    """Empty lines should be silently skipped."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        '\n'
        '{"id":"valid","timestamp":"2025-01-01T00:00:00","type":"cash_movement","payload":{"amount":100}}\n'
        '\n'
        '   \n'
    )

    events = list(read_events(path))
    assert len(events) == 1
    assert events[0].id == "valid"


def test_read_events_nonexistent_file(tmp_path: Path) -> None:
    """Reading a non-existent file should return empty iterator."""
    path = tmp_path / "does_not_exist.jsonl"
    events = list(read_events(path))
    assert events == []


def test_append_events_creates_parent_dirs(tmp_path: Path) -> None:
    """append_events should create parent directories if they don't exist."""
    path = tmp_path / "nested" / "dirs" / "ledger.jsonl"
    event = Event(
        id="test",
        timestamp=datetime(2025, 1, 1),
        type="cash_movement",
        payload={"amount": 100.0},
    )

    append_events(path, [event])

    assert path.exists()
    events = list(read_events(path))
    assert len(events) == 1


def test_append_events_multiple(tmp_path: Path) -> None:
    """Multiple events should be appended correctly."""
    path = tmp_path / "ledger.jsonl"

    events1 = [
        Event(id="1", timestamp=datetime(2025, 1, 1), type="cash_movement", payload={"amount": 100.0}),
        Event(id="2", timestamp=datetime(2025, 1, 2), type="cash_movement", payload={"amount": 200.0}),
    ]
    append_events(path, events1)

    events2 = [
        Event(id="3", timestamp=datetime(2025, 1, 3), type="cash_movement", payload={"amount": 300.0}),
    ]
    append_events(path, events2)

    loaded = list(read_events(path))
    assert len(loaded) == 3
    assert [e.id for e in loaded] == ["1", "2", "3"]


# --- Event Validation Tests ---


def test_event_from_dict_missing_id_raises() -> None:
    """Event.from_dict should raise EventValidationError if id is missing."""
    data = {
        "timestamp": "2025-01-01T00:00:00",
        "type": "cash_movement",
        "payload": {"amount": 100.0},
    }
    with pytest.raises(EventValidationError) as exc_info:
        Event.from_dict(data)
    assert "Missing required field: id" in str(exc_info.value)


def test_event_from_dict_missing_timestamp_raises() -> None:
    """Event.from_dict should raise EventValidationError if timestamp is missing."""
    data = {
        "id": "test-id",
        "type": "cash_movement",
        "payload": {"amount": 100.0},
    }
    with pytest.raises(EventValidationError) as exc_info:
        Event.from_dict(data)
    assert "Missing required field: timestamp" in str(exc_info.value)


def test_event_from_dict_missing_type_raises() -> None:
    """Event.from_dict should raise EventValidationError if type is missing."""
    data = {
        "id": "test-id",
        "timestamp": "2025-01-01T00:00:00",
        "payload": {"amount": 100.0},
    }
    with pytest.raises(EventValidationError) as exc_info:
        Event.from_dict(data)
    assert "Missing required field: type" in str(exc_info.value)


def test_event_from_dict_invalid_type_raises() -> None:
    """Event.from_dict should raise EventValidationError for invalid event type."""
    data = {
        "id": "test-id",
        "timestamp": "2025-01-01T00:00:00",
        "type": "invalid_event_type",
        "payload": {},
    }
    with pytest.raises(EventValidationError) as exc_info:
        Event.from_dict(data)
    assert "Invalid event type: invalid_event_type" in str(exc_info.value)


def test_event_from_dict_malformed_timestamp_raises() -> None:
    """Event.from_dict should raise EventValidationError for invalid timestamp format."""
    data = {
        "id": "test-id",
        "timestamp": "not-a-timestamp",
        "type": "cash_movement",
        "payload": {},
    }
    with pytest.raises(EventValidationError) as exc_info:
        Event.from_dict(data)
    assert "Invalid timestamp format" in str(exc_info.value)


def test_event_from_dict_valid_dividend_event() -> None:
    """Dividend event type should be valid."""
    data = {
        "id": "div-1",
        "timestamp": "2025-01-15T00:00:00",
        "type": "dividend",
        "payload": {
            "symbol": "AAPL",
            "dividend_amount": 50.0,
            "dividend_per_share": 0.5,
        },
    }
    event = Event.from_dict(data)
    assert event.type == "dividend"
    assert event.payload["symbol"] == "AAPL"
    assert event.payload["dividend_amount"] == 50.0


def test_valid_event_types_includes_all_types() -> None:
    """VALID_EVENT_TYPES should include all expected event types."""
    expected = {
        "init_position",
        "trade_add",
        "cash_movement",
        "generic_trade",
        "config_change",
        "correction",
        "dividend",
    }
    assert set(VALID_EVENT_TYPES) == expected


