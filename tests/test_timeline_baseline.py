from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from marketwatch.core.events import Event
from marketwatch.core.timeline import build_daily_series
from marketwatch.prices.base import OHLC, PriceProvider, Split


class FakeProvider(PriceProvider):
    def __init__(self) -> None:
        self.ohlc: dict[tuple[str, date], OHLC] = {}
        self.splits: dict[tuple[str, date], float] = {}

    def set_price(self, symbol: str, d: date, close: float) -> None:
        self.ohlc[(symbol, d)] = OHLC(
            date=d,
            open=close,
            high=close,
            low=close,
            close=close,
        )

    def set_split(self, symbol: str, d: date, ratio: float) -> None:
        self.splits[(symbol, d)] = ratio

    def get_ohlc(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[OHLC]:
        out: list[OHLC] = []
        for (sym, d), bar in sorted(self.ohlc.items(), key=lambda x: x[0][1]):
            if sym != symbol:
                continue
            if start <= d <= end:
                out.append(bar)
        return out

    def get_dividends(self, symbol: str, start: date, end: date) -> list[object]:
        return []

    def get_splits(self, symbol: str, start: date, end: date) -> list[Split]:
        out: list[Split] = []
        for (sym, d), ratio in sorted(self.splits.items(), key=lambda x: x[0][1]):
            if sym != symbol:
                continue
            if start <= d <= end:
                out.append(Split(date=d, ratio=ratio))
        return out


def test_build_daily_series_with_cash_and_aapl_holiday_start() -> None:
    # Init date is a holiday; first trading day is 2025-12-26.
    init_date = date(2025, 12, 25)
    first_trading = date(2025, 12, 26)
    last_trading = date(2025, 12, 30)

    events = [
        Event(
            id="cash",
            timestamp=datetime(2025, 12, 25),
            type="cash_movement",
            payload={"amount": 1000.0},
            note=None,
        ),
        Event(
            id="aapl-init",
            timestamp=datetime(2025, 12, 25),
            type="init_position",
            payload={"symbol": "AAPL", "quantity": 1.0, "cost_price": 180.0},
            note=None,
        ),
    ]

    provider = FakeProvider()
    # AAPL prices.
    provider.set_price("AAPL", first_trading, 180.0)
    provider.set_price("AAPL", date(2025, 12, 29), 190.0)
    provider.set_price("AAPL", last_trading, 200.0)
    # SPY prices (used for baselines and trading calendar).
    provider.set_price("SPY", first_trading, 100.0)
    provider.set_price("SPY", date(2025, 12, 29), 101.0)
    provider.set_price("SPY", last_trading, 102.0)
    # QQQ prices.
    provider.set_price("QQQ", first_trading, 50.0)
    provider.set_price("QQQ", date(2025, 12, 29), 51.0)
    provider.set_price("QQQ", last_trading, 52.0)

    bundle = build_daily_series(
        events_raw=events,
        provider=provider,
        fd_rate=0.0,
        start_date=init_date,
        end_date=last_trading,
    )
    assert bundle is not None

    # Trading days should start from first_trading.
    assert bundle.dates[0] == first_trading
    assert bundle.dates[-1] == last_trading

    # Portfolio value should be cash + AAPL mark-to-market.
    start_val = bundle.portfolio[0]
    end_val = bundle.portfolio[-1]
    assert start_val == 1000.0 + 180.0
    assert end_val == 1000.0 + 200.0


def test_build_daily_series_applies_stock_splits() -> None:
    init_date = date(2025, 6, 10)
    split_date = date(2025, 6, 12)
    last_trading = date(2025, 6, 13)

    events = [
        Event(
            id="cash",
            timestamp=datetime(2025, 6, 10),
            type="cash_movement",
            payload={"amount": 0.0},
            note=None,
        ),
        Event(
            id="nvda-init",
            timestamp=datetime(2025, 6, 10),
            type="init_position",
            payload={"symbol": "NVDA", "quantity": 10.0, "cost_price": 100.0},
            note=None,
        ),
    ]

    provider = FakeProvider()
    # NVDA prices: pre-split 100, post-split 50 with 2:1 split ->
    # portfolio value should remain 1000.
    provider.set_price("NVDA", init_date, 100.0)
    provider.set_price("NVDA", split_date, 50.0)
    provider.set_price("NVDA", last_trading, 50.0)
    provider.set_split("NVDA", split_date, 2.0)

    # SPY prices (used for baselines and trading calendar).
    provider.set_price("SPY", init_date, 100.0)
    provider.set_price("SPY", split_date, 101.0)
    provider.set_price("SPY", last_trading, 102.0)
    # QQQ prices.
    provider.set_price("QQQ", init_date, 50.0)
    provider.set_price("QQQ", split_date, 51.0)
    provider.set_price("QQQ", last_trading, 52.0)

    bundle = build_daily_series(
        events_raw=events,
        provider=provider,
        fd_rate=0.0,
        start_date=init_date,
        end_date=last_trading,
    )
    assert bundle is not None

    # After the split, quantity should double and value remain constant.
    values = bundle.portfolio
    # We only care about pre- and post-split trading days; any intermediate
    # calendar days without prices will stay flat at the last known value.
    assert values[0] == values[2] == values[3] == 10.0 * 100.0


