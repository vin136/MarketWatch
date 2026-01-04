from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from marketwatch.core.events import Event
from marketwatch.storage.ledger import append_events, read_events


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


