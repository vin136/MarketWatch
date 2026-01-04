from __future__ import annotations

from pathlib import Path
import os

from marketwatch.storage.paths import (
    get_base_dir,
    get_current_portfolio_dir,
    set_current_portfolio_dir,
    get_portfolio_dir,
)


def test_current_portfolio_roundtrip(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("MARKETWATCH_HOME", str(tmp_path))
    base = get_base_dir()
    assert base == tmp_path

    portfolio_dir = tmp_path / "example"
    portfolio_dir.mkdir()
    set_current_portfolio_dir(portfolio_dir)

    current = get_current_portfolio_dir()
    assert current == portfolio_dir

    resolved = get_portfolio_dir(name=None, directory=None)
    assert resolved == portfolio_dir


