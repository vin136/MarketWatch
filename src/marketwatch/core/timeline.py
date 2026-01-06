from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from marketwatch.core.events import Event, apply_corrections
from marketwatch.prices.base import OHLC, PriceProvider


@dataclass(slots=True)
class DailySeriesBundle:
    dates: list[date]
    portfolio: list[float]
    baseline_spy: list[float]
    baseline_qqq: list[float]
    baseline_fd: list[float]


def _collect_symbols(events: Iterable[Event]) -> list[str]:
    symbols: set[str] = set()
    for event in events:
        if event.type in ("init_position", "trade_add"):
            symbol = event.payload.get("symbol")
            if symbol:
                symbols.add(str(symbol))
    return sorted(symbols)


def _prices_by_date(
    provider: PriceProvider,
    symbol: str,
    start: date,
    end: date,
) -> dict[date, float]:
    ohlc: list[OHLC] = provider.get_ohlc(symbol, start, end)
    return {item.date: item.close for item in ohlc}


def build_daily_series(
    events_raw: Iterable[Event],
    provider: PriceProvider,
    fd_rate: float = 0.05,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DailySeriesBundle | None:
    events = apply_corrections(list(events_raw))
    if not events:
        return None

    events.sort(key=lambda e: e.timestamp)

    if start_date is None:
        start_date = events[0].timestamp.date()
    if end_date is None:
        end_date = date.today()
    if start_date > end_date:
        return None

    symbols = _collect_symbols(events)

    # Map of date -> events for that date (full range).
    day_events: dict[date, list[Event]] = {}
    for event in events:
        d = event.timestamp.date()
        if d > end_date:
            continue
        day_events.setdefault(d, []).append(event)

    # Fetch SPY to determine actual trading date range (handles weekends/holidays).
    # Look back a few extra days to capture the last trading day before start_date.
    lookback_start = start_date - timedelta(days=10)
    spy_prices_full = _prices_by_date(provider, "SPY", lookback_start, end_date)
    if not spy_prices_full:
        return None

    trading_dates = sorted(d for d in spy_prices_full.keys() if d >= start_date)
    if not trading_dates:
        return None

    series_start = trading_dates[0]
    series_end = trading_dates[-1]

    # Pre-fetch symbol prices including lookback period for init valuation.
    price_map: dict[str, dict[date, float]] = {
        sym: _prices_by_date(provider, sym, lookback_start, series_end)
        for sym in symbols
    }
    spy_prices = {d: p for d, p in spy_prices_full.items() if series_start <= d <= series_end}
    qqq_prices = _prices_by_date(provider, "QQQ", lookback_start, series_end)

    # Pre-fetch splits so that stock splits are reflected in portfolio value.
    splits_map: dict[str, dict[date, float]] = {}
    for sym in symbols:
        splits = provider.get_splits(sym, series_start, series_end)
        if not splits:
            continue
        per_day: dict[date, float] = {}
        for sp in splits:
            # Ignore degenerate or no-op splits.
            if sp.ratio is None or sp.ratio <= 0.0 or sp.ratio == 1.0:
                continue
            per_day[sp.date] = sp.ratio
        if per_day:
            splits_map[sym] = per_day

    dates: list[date] = []
    portfolio_values: list[float] = []
    spy_series: list[float] = []
    qqq_series: list[float] = []
    fd_series: list[float] = []

    positions: dict[str, float] = {sym: 0.0 for sym in symbols}
    cash = 0.0
    spy_units = 0.0
    qqq_units = 0.0
    fd_balance = 0.0

    # Track if there are events before the first trading day.
    has_pre_trading_events = False

    # First, process all events strictly before the first trading day to build initial state.
    current = start_date
    while current < series_start:
        todays_events = day_events.get(current, [])
        for event in todays_events:
            has_pre_trading_events = True
            if event.type == "cash_movement":
                amount = float(event.payload.get("amount", 0.0) or 0.0)
                cash += amount
            elif event.type == "generic_trade":
                pnl = float(event.payload.get("pnl", 0.0) or 0.0)
                cash += pnl
            elif event.type in ("init_position", "trade_add"):
                symbol = event.payload.get("symbol")
                if not symbol:
                    continue
                sym = str(symbol)
                if sym not in positions:
                    positions[sym] = 0.0
                if event.type == "init_position":
                    qty = float(event.payload.get("quantity", 0.0) or 0.0)
                    positions[sym] = positions.get(sym, 0.0) + qty
                else:
                    delta = float(event.payload.get("quantity_delta", 0.0) or 0.0)
                    positions[sym] = positions.get(sym, 0.0) + delta
        current += timedelta(days=1)

    # If there were events before the first trading day, prepend a "day 0" using the
    # most recent available market prices (i.e., last trading day before init date).
    if has_pre_trading_events:
        # Find the last trading day before series_start to get prices.
        last_trading_before_init = None
        for d in sorted(spy_prices_full.keys(), reverse=True):
            if d < series_start:
                last_trading_before_init = d
                break

        if last_trading_before_init is not None:
            # Value positions at the last available market prices before init.
            init_holdings_value = 0.0
            for sym, qty in positions.items():
                if qty == 0.0:
                    continue
                sym_prices = price_map.get(sym, {})
                # Find the most recent price on or before last_trading_before_init.
                price_for_init = None
                for d in sorted(sym_prices.keys(), reverse=True):
                    if d <= last_trading_before_init:
                        price_for_init = sym_prices[d]
                        break
                if price_for_init is not None:
                    init_holdings_value += qty * price_for_init

            init_value = cash + init_holdings_value
            if init_value > 0:
                dates.append(start_date)
                portfolio_values.append(init_value)
                # Baselines start at same value for fair comparison.
                spy_series.append(init_value)
                qqq_series.append(init_value)
                fd_series.append(init_value)
                # Initialize baseline units using last trading day prices.
                spy_price_init = spy_prices_full.get(last_trading_before_init)
                qqq_price_init = qqq_prices.get(last_trading_before_init)
                if spy_price_init:
                    spy_units = init_value / spy_price_init
                if qqq_price_init:
                    qqq_units = init_value / qqq_price_init
                fd_balance = init_value

    # Now build daily series from first trading day onwards.
    current = series_start
    first_day = not has_pre_trading_events  # Not first day if we already added init value
    while current <= series_end:
        todays_events = day_events.get(current, [])
        external_flow = 0.0

        for event in todays_events:
            if event.type == "cash_movement":
                amount = float(event.payload.get("amount", 0.0) or 0.0)
                cash += amount
                external_flow += amount
            elif event.type == "generic_trade":
                pnl = float(event.payload.get("pnl", 0.0) or 0.0)
                cash += pnl
            elif event.type in ("init_position", "trade_add"):
                symbol = event.payload.get("symbol")
                if not symbol:
                    continue
                sym = str(symbol)
                if sym not in positions:
                    positions[sym] = 0.0
                    price_map[sym] = _prices_by_date(
                        provider,
                        sym,
                        start_date,
                        end_date,
                    )
                if event.type == "init_position":
                    qty = float(event.payload.get("quantity", 0.0) or 0.0)
                    positions[sym] = positions.get(sym, 0.0) + qty
                else:
                    delta = float(event.payload.get("quantity_delta", 0.0) or 0.0)
                    positions[sym] = positions.get(sym, 0.0) + delta

        # Apply stock splits effective on this date to current positions.
        for sym, qty in list(positions.items()):
            if qty == 0.0:
                continue
            per_day_splits = splits_map.get(sym)
            if not per_day_splits:
                continue
            ratio = per_day_splits.get(current)
            if ratio is None or ratio <= 0.0 or ratio == 1.0:
                continue
            positions[sym] = qty * ratio

        holdings_value = 0.0
        for sym, qty in positions.items():
            if qty == 0.0:
                continue
            price_for_day = price_map.get(sym, {}).get(current)
            if price_for_day is None:
                continue
            holdings_value += qty * price_for_day

        net_liq = cash + holdings_value

        # Baselines.
        spy_price = spy_prices.get(current)
        qqq_price = qqq_prices.get(current)

        if first_day:
            if spy_price:
                spy_units = net_liq / spy_price
            if qqq_price:
                qqq_units = net_liq / qqq_price
            fd_balance = net_liq
            spy_val = net_liq
            qqq_val = net_liq
        else:
            if spy_price:
                if external_flow != 0.0:
                    spy_units += external_flow / spy_price
                spy_val = spy_units * spy_price
            else:
                spy_val = spy_series[-1]

            if qqq_price:
                if external_flow != 0.0:
                    qqq_units += external_flow / qqq_price
                qqq_val = qqq_units * qqq_price
            else:
                qqq_val = qqq_series[-1]

            daily_fd_rate = fd_rate / 252.0
            fd_balance = fd_balance * (1.0 + daily_fd_rate) + external_flow

        dates.append(current)
        portfolio_values.append(net_liq)
        spy_series.append(spy_val)
        qqq_series.append(qqq_val)
        fd_series.append(fd_balance)

        first_day = False
        current += timedelta(days=1)

    return DailySeriesBundle(
        dates=dates,
        portfolio=portfolio_values,
        baseline_spy=spy_series,
        baseline_qqq=qqq_series,
        baseline_fd=fd_series,
    )


