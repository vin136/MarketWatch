from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable
import csv
import types

import pytest

from marketwatch.prices.yahoo import YahooPriceProvider
from marketwatch.prices.base import OHLC

yf = pytest.importorskip("yfinance")


class _FakeHistory:
    def __init__(self, rows: list[tuple[date, float]]) -> None:
        self._rows = rows

    def iterrows(self) -> Iterable[tuple[Any, dict[str, float]]]:
        for d, close in self._rows:
            yield types.SimpleNamespace(to_pydatetime=lambda d=d: d), {
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Volume": 100.0,
            }


class _FakeTicker:
    def __init__(self, rows: list[tuple[date, float]]) -> None:
        self._rows = rows

    def history(self, start: date, end: date, auto_adjust: bool = False) -> _FakeHistory:
        filtered = [(d, c) for d, c in self._rows if start <= d <= end]
        return _FakeHistory(filtered)

    @property
    def dividends(self) -> dict[date, float]:
        return {}

    @property
    def splits(self) -> dict[date, float]:
        return {}


def test_get_ohlc_cache_consistency_ok(tmp_path: Path, monkeypatch: Any) -> None:
    symbol = "TEST"
    start = date(2025, 1, 1)
    end = date(2025, 1, 10)

    cache_dir = tmp_path / "cache"
    provider = YahooPriceProvider(cache_dir=cache_dir)
    cache_path = cache_dir / f"{symbol}__ohlc.csv"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Seed cache with one bar.
    with cache_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        writer.writerow(["2025-01-05", 100.0, 100.0, 100.0, 100.0, 100.0])

    rows = [(date(2025, 1, 5), 100.0), (date(2025, 1, 6), 101.0)]
    monkeypatch.setattr(yf, "Ticker", lambda _: _FakeTicker(rows))

    result = provider.get_ohlc(symbol, start, end)
    dates = [bar.date for bar in result]
    assert date(2025, 1, 5) in dates
    assert date(2025, 1, 6) in dates


def test_get_ohlc_cache_inconsistency_raises(tmp_path: Path, monkeypatch: Any) -> None:
    symbol = "TEST"
    start = date(2025, 1, 1)
    end = date(2025, 1, 10)

    cache_dir = tmp_path / "cache"
    provider = YahooPriceProvider(cache_dir=cache_dir)
    cache_path = cache_dir / f"{symbol}__ohlc.csv"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Seed cache with one bar that conflicts with fetched history.
    with cache_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        writer.writerow(["2025-01-05", 100.0, 100.0, 100.0, 100.0, 100.0])

    rows = [(date(2025, 1, 5), 110.0)]
    monkeypatch.setattr(yf, "Ticker", lambda _: _FakeTicker(rows))

    try:
        provider.get_ohlc(symbol, start, end)
    except RuntimeError:
        return

    raise AssertionError("Expected RuntimeError due to inconsistent cache and fetched data.")


