from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from typer.testing import CliRunner

from marketwatch.cli.app import app
from marketwatch.core.events import Event, apply_corrections
from marketwatch.core.state import build_snapshot
from marketwatch.storage.config import load_config, save_config, Config
from marketwatch.storage.ledger import append_events, read_events


def test_apply_corrections_invalidate() -> None:
    ts = datetime(2025, 1, 1, 12, 0, 0)
    base = Event(
        id="e1",
        timestamp=ts,
        type="cash_movement",
        payload={"amount": 100.0},
    )
    corr = Event(
        id="e2",
        timestamp=ts,
        type="correction",
        payload={
            "target_event_id": "e1",
            "correction_type": "invalidate",
            "new_payload": None,
        },
    )
    effective = apply_corrections([base, corr])
    assert effective == []


def test_edit_cli_invalidates_event(tmp_path: Path, monkeypatch: object) -> None:
    portfolio_dir = tmp_path / "p1"
    portfolio_dir.mkdir()
    ledger_path = portfolio_dir / "ledger.jsonl"

    ts = datetime(2025, 1, 1, 12, 0, 0)
    event = Event(
        id=str(uuid.uuid4()),
        timestamp=ts,
        type="cash_movement",
        payload={"amount": 100.0},
    )
    append_events(ledger_path, [event])

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["edit", "--dir", str(portfolio_dir), "--last", "1"],
        input="0\n",
    )
    assert result.exit_code == 0

    events = list(read_events(ledger_path))
    snapshot = build_snapshot(events)
    assert snapshot.cash == 0.0


def test_config_set_target_roundtrip(tmp_path: Path, monkeypatch: object) -> None:
    portfolio_dir = tmp_path / "p2"
    portfolio_dir.mkdir()
    config_path = portfolio_dir / "config.json"
    save_config(config_path, Config(name="p2"))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "config",
            "set-target",
            "AAPL",
            "--buy",
            "150",
            "--sell",
            "220",
            "--intrinsic",
            "210",
            "--max-weight",
            "0.1",
            "--dir",
            str(portfolio_dir),
        ],
    )
    assert result.exit_code == 0

    cfg = load_config(config_path)
    assert cfg is not None
    assert "AAPL" in cfg.symbols
    sym_cfg = cfg.symbols["AAPL"]
    assert sym_cfg.buy_target == 150.0
    assert sym_cfg.sell_target == 220.0
    assert sym_cfg.intrinsic_value == 210.0
    assert sym_cfg.max_weight == 0.1


