"""Shared test fixtures for MarketWatch tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
import uuid

import pytest

from marketwatch.core.events import Event, EventPayload
from marketwatch.core.state import PortfolioSnapshot, Position
from marketwatch.prices.base import OHLC, PriceProvider, Split, Dividend


class MockPriceProvider(PriceProvider):
    """
    Flexible mock price provider for testing.

    Supports multiple ways to set prices:
    - set_price(symbol, date, close) - for simple close-only prices
    - set_ohlc(symbol, date, open, high, low, close) - for full OHLC
    - series[symbol] = [OHLC, ...] - for bulk price series
    """

    def __init__(self) -> None:
        self.ohlc: dict[tuple[str, date], OHLC] = {}
        self.splits: dict[tuple[str, date], float] = {}
        self.dividends: dict[tuple[str, date], float] = {}
        self.series: dict[str, list[OHLC]] = {}

    def set_price(self, symbol: str, d: date, close: float) -> None:
        """Set a simple close price (open/high/low = close)."""
        self.ohlc[(symbol, d)] = OHLC(
            date=d,
            open=close,
            high=close,
            low=close,
            close=close,
        )

    def set_ohlc(
        self,
        symbol: str,
        d: date,
        open_: float,
        high: float,
        low: float,
        close: float,
    ) -> None:
        """Set full OHLC bar."""
        self.ohlc[(symbol, d)] = OHLC(
            date=d, open=open_, high=high, low=low, close=close
        )

    def set_split(self, symbol: str, d: date, ratio: float) -> None:
        """Set a stock split."""
        self.splits[(symbol, d)] = ratio

    def set_dividend(self, symbol: str, d: date, amount: float) -> None:
        """Set a dividend payment."""
        self.dividends[(symbol, d)] = amount

    def get_ohlc(self, symbol: str, start: date, end: date) -> list[OHLC]:
        # First check if there's a series for this symbol
        if symbol in self.series:
            return [
                bar
                for bar in self.series[symbol]
                if start <= bar.date <= end
            ]
        # Otherwise use individual OHLC entries
        out: list[OHLC] = []
        for (sym, d), bar in sorted(self.ohlc.items(), key=lambda x: x[0][1]):
            if sym != symbol:
                continue
            if start <= d <= end:
                out.append(bar)
        return out

    def get_dividends(self, symbol: str, start: date, end: date) -> list[Dividend]:
        out: list[Dividend] = []
        for (sym, d), amount in sorted(self.dividends.items(), key=lambda x: x[0][1]):
            if sym != symbol:
                continue
            if start <= d <= end:
                out.append(Dividend(date=d, amount=amount))
        return out

    def get_splits(self, symbol: str, start: date, end: date) -> list[Split]:
        out: list[Split] = []
        for (sym, d), ratio in sorted(self.splits.items(), key=lambda x: x[0][1]):
            if sym != symbol:
                continue
            if start <= d <= end:
                out.append(Split(date=d, ratio=ratio))
        return out


@pytest.fixture
def mock_provider() -> MockPriceProvider:
    """Return a fresh MockPriceProvider instance."""
    return MockPriceProvider()


@pytest.fixture
def tmp_portfolio_dir(tmp_path: Path) -> Path:
    """
    Create a temporary portfolio directory structure.

    Returns a Path to a portfolio directory containing:
    - ledger.jsonl (empty)
    - config.json (default config)
    - price_cache/ (empty directory)
    """
    portfolio_dir = tmp_path / "test_portfolio"
    portfolio_dir.mkdir()
    (portfolio_dir / "ledger.jsonl").touch()
    (portfolio_dir / "price_cache").mkdir()

    # Create minimal config
    config = {
        "fd_rate": 0.05,
        "default_max_weight": 0.05,
        "whatsup_lookback_days": 252,
        "invest_lookback_years": 5,
        "symbol_configs": {},
    }
    import json
    (portfolio_dir / "config.json").write_text(json.dumps(config))

    return portfolio_dir


def make_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    note: str | None = None,
    timestamp: datetime | None = None,
    event_id: str | None = None,
) -> Event:
    """Helper to create test events with sensible defaults."""
    return Event(
        id=event_id or str(uuid.uuid4()),
        timestamp=timestamp or datetime.now(),
        type=event_type,
        payload=EventPayload(**(payload or {})),
        note=note,
    )


@pytest.fixture
def sample_events() -> list[Event]:
    """
    Return a list of sample events for testing.

    Contains:
    - Cash movement: $10,000 deposit
    - Init position: 100 AAPL @ $150
    - Trade: Buy 50 GOOGL @ $140
    """
    base_time = datetime(2025, 1, 1, 9, 0, 0)
    return [
        make_event(
            "cash_movement",
            {"amount": 10000.0},
            timestamp=base_time,
            event_id="evt-cash-1",
        ),
        make_event(
            "init_position",
            {"symbol": "AAPL", "quantity": 100.0, "cost_price": 150.0},
            timestamp=base_time + timedelta(seconds=1),
            event_id="evt-aapl-init",
        ),
        make_event(
            "trade_add",
            {"symbol": "GOOGL", "quantity_delta": 50.0, "price": 140.0},
            timestamp=base_time + timedelta(seconds=2),
            event_id="evt-googl-buy",
        ),
    ]


@pytest.fixture
def sample_snapshot() -> PortfolioSnapshot:
    """
    Return a sample PortfolioSnapshot for testing analytics.

    Contains:
    - AAPL: 100 shares, $15,000 cost
    - GOOGL: 50 shares, $7,000 cost
    - Cash: $3,000
    """
    return PortfolioSnapshot(
        positions={
            "AAPL": Position(symbol="AAPL", quantity=100.0, total_cost=15000.0),
            "GOOGL": Position(symbol="GOOGL", quantity=50.0, total_cost=7000.0),
        },
        cash=3000.0,
    )


def generate_price_series(
    symbol: str,
    start: date,
    days: int,
    initial_price: float = 100.0,
    daily_return: float = 0.001,
) -> list[OHLC]:
    """
    Generate a synthetic price series for testing.

    Args:
        symbol: Stock symbol (for reference, not stored in OHLC)
        start: Start date
        days: Number of days to generate
        initial_price: Starting price
        daily_return: Daily return rate (e.g., 0.001 = 0.1%)

    Returns:
        List of OHLC bars
    """
    prices: list[OHLC] = []
    current = start
    price = initial_price

    for _ in range(days):
        prices.append(
            OHLC(
                date=current,
                open=price,
                high=price * 1.01,  # 1% intraday range
                low=price * 0.99,
                close=price,
            )
        )
        price *= 1 + daily_return
        current += timedelta(days=1)

    return prices
