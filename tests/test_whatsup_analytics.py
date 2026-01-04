from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from marketwatch.core.analytics import compute_whatsup
from marketwatch.core.state import PortfolioSnapshot, Position
from marketwatch.prices.base import OHLC, PriceProvider


class FakeProvider(PriceProvider):
    def __init__(self) -> None:
        self.series: dict[str, list[OHLC]] = {}

    def get_ohlc(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[OHLC]:
        return self.series.get(symbol, [])

    def get_dividends(self, symbol: str, start: date, end: date) -> list[object]:
        return []

    def get_splits(self, symbol: str, start: date, end: date) -> list[object]:
        return []


def test_compute_whatsup_basic() -> None:
    snapshot = PortfolioSnapshot(
        positions={"AAA": Position(symbol="AAA", quantity=1.0)},
        cash=0.0,
    )
    provider = FakeProvider()
    today = date(2025, 1, 31)
    start = today - timedelta(days=30)

    prices: list[OHLC] = []
    current = start
    price = 100.0
    while current <= today:
        prices.append(
            OHLC(
                date=current,
                open=price,
                high=price,
                low=price,
                close=price,
            )
        )
        price *= 1.001
        current += timedelta(days=1)

    provider.series["AAA"] = prices

    rows = compute_whatsup(
        snapshot=snapshot,
        symbols_extra=[],
        provider=provider,
        lookback_days=20,
        today=today,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "AAA"
    assert row.quantile is not None


