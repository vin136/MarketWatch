"""Tests for dividend tracking functionality."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from marketwatch.core.events import Event
from marketwatch.core.state import build_snapshot
from marketwatch.storage.ledger import append_events, read_events


def test_dividend_event_adds_to_cash() -> None:
    """Dividend events should add to cash balance."""
    events = [
        Event(
            id="cash-1",
            timestamp=datetime(2025, 1, 1),
            type="cash_movement",
            payload={"amount": 1000.0},
        ),
        Event(
            id="init-aapl",
            timestamp=datetime(2025, 1, 1),
            type="init_position",
            payload={"symbol": "AAPL", "quantity": 100.0, "cost_price": 150.0},
        ),
        Event(
            id="div-1",
            timestamp=datetime(2025, 1, 15),
            type="dividend",
            payload={
                "symbol": "AAPL",
                "dividend_amount": 50.0,
                "dividend_per_share": 0.5,
            },
        ),
    ]

    snapshot = build_snapshot(events)

    # Cash should be initial 1000 + 50 dividend
    assert snapshot.cash == 1050.0
    # Position should remain unchanged
    assert "AAPL" in snapshot.positions
    assert snapshot.positions["AAPL"].quantity == 100.0


def test_multiple_dividends_accumulate() -> None:
    """Multiple dividend events should accumulate correctly."""
    events = [
        Event(
            id="cash-1",
            timestamp=datetime(2025, 1, 1),
            type="cash_movement",
            payload={"amount": 500.0},
        ),
        Event(
            id="init-aapl",
            timestamp=datetime(2025, 1, 1),
            type="init_position",
            payload={"symbol": "AAPL", "quantity": 100.0, "cost_price": 150.0},
        ),
        Event(
            id="div-1",
            timestamp=datetime(2025, 3, 15),
            type="dividend",
            payload={"symbol": "AAPL", "dividend_amount": 24.0, "dividend_per_share": 0.24},
        ),
        Event(
            id="div-2",
            timestamp=datetime(2025, 6, 15),
            type="dividend",
            payload={"symbol": "AAPL", "dividend_amount": 25.0, "dividend_per_share": 0.25},
        ),
        Event(
            id="div-3",
            timestamp=datetime(2025, 9, 15),
            type="dividend",
            payload={"symbol": "AAPL", "dividend_amount": 25.0, "dividend_per_share": 0.25},
        ),
    ]

    snapshot = build_snapshot(events)

    # Cash = 500 + 24 + 25 + 25 = 574
    assert snapshot.cash == 574.0


def test_dividend_event_roundtrip(tmp_path: Path) -> None:
    """Dividend events should serialize and deserialize correctly."""
    ledger_path = tmp_path / "ledger.jsonl"

    original_event = Event(
        id="div-test",
        timestamp=datetime(2025, 6, 15, 10, 30, 0),
        type="dividend",
        payload={
            "symbol": "MSFT",
            "dividend_amount": 75.50,
            "dividend_per_share": 0.755,
        },
        note="Q2 dividend",
    )

    append_events(ledger_path, [original_event])
    loaded_events = list(read_events(ledger_path))

    assert len(loaded_events) == 1
    loaded = loaded_events[0]
    assert loaded.id == "div-test"
    assert loaded.type == "dividend"
    assert loaded.payload["symbol"] == "MSFT"
    assert loaded.payload["dividend_amount"] == 75.50
    assert loaded.payload["dividend_per_share"] == 0.755
    assert loaded.note == "Q2 dividend"


def test_dividend_with_invalid_amount_skipped() -> None:
    """Dividend events with invalid amounts should be skipped."""
    events = [
        Event(
            id="cash-1",
            timestamp=datetime(2025, 1, 1),
            type="cash_movement",
            payload={"amount": 1000.0},
        ),
        Event(
            id="div-invalid",
            timestamp=datetime(2025, 1, 15),
            type="dividend",
            payload={
                "symbol": "AAPL",
                "dividend_amount": float("nan"),  # Invalid
                "dividend_per_share": 0.5,
            },
        ),
    ]

    snapshot = build_snapshot(events)

    # Cash should only be initial amount (invalid dividend skipped)
    assert snapshot.cash == 1000.0


def test_dividend_for_multiple_symbols() -> None:
    """Dividends for multiple symbols should be tracked separately."""
    events = [
        Event(
            id="cash-1",
            timestamp=datetime(2025, 1, 1),
            type="cash_movement",
            payload={"amount": 0.0},
        ),
        Event(
            id="init-aapl",
            timestamp=datetime(2025, 1, 1),
            type="init_position",
            payload={"symbol": "AAPL", "quantity": 100.0, "cost_price": 150.0},
        ),
        Event(
            id="init-msft",
            timestamp=datetime(2025, 1, 1),
            type="init_position",
            payload={"symbol": "MSFT", "quantity": 50.0, "cost_price": 300.0},
        ),
        Event(
            id="div-aapl",
            timestamp=datetime(2025, 3, 15),
            type="dividend",
            payload={"symbol": "AAPL", "dividend_amount": 24.0, "dividend_per_share": 0.24},
        ),
        Event(
            id="div-msft",
            timestamp=datetime(2025, 3, 20),
            type="dividend",
            payload={"symbol": "MSFT", "dividend_amount": 37.50, "dividend_per_share": 0.75},
        ),
    ]

    snapshot = build_snapshot(events)

    # Cash = 0 + 24 (AAPL) + 37.50 (MSFT) = 61.50
    assert snapshot.cash == 61.50
    # Positions should remain unchanged
    assert snapshot.positions["AAPL"].quantity == 100.0
    assert snapshot.positions["MSFT"].quantity == 50.0
