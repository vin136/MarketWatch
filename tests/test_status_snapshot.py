from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from typer.testing import CliRunner

from marketwatch.cli.app import app
from marketwatch.core.events import Event
from marketwatch.core.state import build_snapshot
from marketwatch.storage.ledger import append_events, read_events


def _make_sample_events() -> list[Event]:
    ts = datetime(2025, 1, 1, 12, 0, 0)
    return [
        Event(
            id=str(uuid.uuid4()),
            timestamp=ts,
            type="cash_movement",
            payload={"amount": 1000.0},
        ),
        Event(
            id=str(uuid.uuid4()),
            timestamp=ts,
            type="init_position",
            payload={"symbol": "AAPL", "quantity": 10.0, "cost_price": 150.0},
        ),
        Event(
            id=str(uuid.uuid4()),
            timestamp=ts,
            type="trade_add",
            payload={"symbol": "AAPL", "quantity_delta": 5.0, "price": 160.0},
        ),
    ]


def test_build_snapshot_basic(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    events = _make_sample_events()
    append_events(path, events)

    loaded_events = list(read_events(path))
    snapshot = build_snapshot(loaded_events)

    assert snapshot.cash == 1000.0
    assert "AAPL" in snapshot.positions
    pos = snapshot.positions["AAPL"]
    assert pos.quantity == 15.0
    assert pos.cost_basis is not None
    assert round(pos.cost_basis, 2) == round((10 * 150 + 5 * 160) / 15, 2)


def test_status_cli_no_ui(tmp_path: Path, monkeypatch: object) -> None:
    portfolio_dir = tmp_path / "test"
    portfolio_dir.mkdir()
    ledger_path = portfolio_dir / "ledger.jsonl"
    append_events(ledger_path, _make_sample_events())

    # Force CLI to use this directory directly.
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "status",
            "--no-ui",
            "--dir",
            str(portfolio_dir),
        ],
    )
    assert result.exit_code == 0
    assert "AAPL" in result.stdout
    assert "Cash:" in result.stdout


