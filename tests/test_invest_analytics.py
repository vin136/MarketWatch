from __future__ import annotations

from datetime import date, timedelta

from marketwatch.core.analytics import compute_invest_suggestions
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


def test_compute_invest_suggestions_basic() -> None:
    snapshot = PortfolioSnapshot(
        positions={
            "AAA": Position(symbol="AAA", quantity=10.0),
            "BBB": Position(symbol="BBB", quantity=5.0),
        },
        cash=0.0,
    )

    provider = FakeProvider()
    today = date(2025, 1, 31)
    start = today - timedelta(days=30)

    prices_aaa: list[OHLC] = []
    prices_bbb: list[OHLC] = []
    current = start
    price_a = 100.0
    price_b = 50.0
    while current <= today:
        prices_aaa.append(
            OHLC(
                date=current,
                open=price_a,
                high=price_a,
                low=price_a,
                close=price_a,
            )
        )
        prices_bbb.append(
            OHLC(
                date=current,
                open=price_b,
                high=price_b,
                low=price_b,
                close=price_b,
            )
        )
        price_a *= 1.001
        price_b *= 1.002
        current += timedelta(days=1)

    provider.series["AAA"] = prices_aaa
    provider.series["BBB"] = prices_bbb

    rows = compute_invest_suggestions(
        snapshot=snapshot,
        provider=provider,
        amount=1000.0,
        lookback_years=1,
    )
    assert rows
    symbols = {row.symbol for row in rows}
    assert symbols == {"AAA", "BBB"}


