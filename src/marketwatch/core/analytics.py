from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence, Mapping
import math
import statistics

from marketwatch.core.state import PortfolioSnapshot
from marketwatch.prices.base import OHLC, PriceProvider


def _daily_returns_from_ohlc(ohlc: Sequence[OHLC]) -> list[float]:
    if len(ohlc) < 2:
        return []
    returns: list[float] = []
    prev_close = ohlc[0].close
    for item in ohlc[1:]:
        if prev_close <= 0.0:
            prev_close = item.close
            continue
        r = (item.close / prev_close) - 1.0
        returns.append(r)
        prev_close = item.close
    return returns


def _quantile(value: float, samples: Sequence[float]) -> float | None:
    if not samples:
        return None
    sorted_vals = sorted(samples)
    count = len(sorted_vals)
    if count == 1:
        return 1.0
    lo = 0
    hi = count
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo / count


@dataclass(slots=True)
class WhatsUpRow:
    symbol: str
    last_return: float
    avg_21d_return: float
    quantile: float | None

    @property
    def extremeness(self) -> float | None:
        if self.quantile is None:
            return None
        return min(self.quantile, 1.0 - self.quantile)


def compute_whatsup(
    snapshot: PortfolioSnapshot,
    symbols_extra: Iterable[str],
    provider: PriceProvider,
    lookback_days: int = 252,
    today: date | None = None,
) -> list[WhatsUpRow]:
    if today is None:
        today = date.today()
    start = today - timedelta(days=lookback_days + 10)

    symbols: set[str] = set(snapshot.positions.keys())
    symbols.update(symbols_extra)

    rows: list[WhatsUpRow] = []
    for symbol in sorted(symbols):
        ohlc = provider.get_ohlc(symbol, start, today)
        if len(ohlc) < 22:
            continue
        rets = _daily_returns_from_ohlc(ohlc)
        if len(rets) < 22:
            continue
        last_ret = rets[-1]
        avg_21 = statistics.mean(rets[-21:])
        q = _quantile(last_ret, rets)
        rows.append(
            WhatsUpRow(
                symbol=symbol,
                last_return=last_ret,
                avg_21d_return=avg_21,
                quantile=q,
            )
        )

    rows.sort(
        key=lambda r: (
            r.extremeness if r.extremeness is not None else math.inf
        )
    )
    return rows


@dataclass(slots=True)
class InvestRow:
    symbol: str
    avg_daily_return: float
    volatility: float
    combined_volatility: float
    vol_change: float


def _compute_daily_returns_for_symbols(
    provider: PriceProvider,
    symbols: Iterable[str],
    start: date,
    end: date,
) -> dict[str, list[float]]:
    returns_by_symbol: dict[str, list[float]] = {}
    for symbol in symbols:
        ohlc = provider.get_ohlc(symbol, start, end)
        rets = _daily_returns_from_ohlc(ohlc)
        if rets:
            returns_by_symbol[symbol] = rets
    return returns_by_symbol


def _align_returns(returns_by_symbol: Mapping[str, list[float]]) -> list[dict[str, float]]:
    if not returns_by_symbol:
        return []
    # Align by truncating to the shortest series.
    min_len = min(len(v) for v in returns_by_symbol.values())
    aligned: list[dict[str, float]] = []
    for i in range(min_len):
        day: dict[str, float] = {}
        for sym, rets in returns_by_symbol.items():
            day[sym] = rets[i]
        aligned.append(day)
    return aligned


def compute_invest_suggestions(
    snapshot: PortfolioSnapshot,
    provider: PriceProvider,
    amount: float,
    lookback_years: int = 5,
) -> list[InvestRow]:
    today = date.today()
    start = date(today.year - lookback_years, today.month, today.day)

    symbols = list(snapshot.positions.keys())
    if not symbols or amount <= 0.0:
        return []

    returns_by_symbol = _compute_daily_returns_for_symbols(
        provider,
        symbols,
        start,
        today,
    )
    aligned = _align_returns(returns_by_symbol)
    if not aligned:
        return []

    # Equal-weight base portfolio for v1.
    base_returns: list[float] = []
    for day in aligned:
        if not day:
            continue
        base_returns.append(sum(day.values()) / float(len(day)))

    if not base_returns:
        return []

    base_vol = statistics.pstdev(base_returns) if len(base_returns) > 1 else 0.0

    # Approximate net liq as sum of unit quantities with price 1.0 for weight calculation.
    total_quantity = sum(pos.quantity for pos in snapshot.positions.values())
    if total_quantity <= 0.0:
        return []

    suggestion_rows: list[InvestRow] = []
    for symbol in symbols:
        sym_rets = returns_by_symbol.get(symbol)
        if not sym_rets:
            continue
        avg_ret = statistics.mean(sym_rets)
        sym_vol = statistics.pstdev(sym_rets) if len(sym_rets) > 1 else 0.0

        position = snapshot.positions[symbol]
        current_weight = position.quantity / total_quantity

        # Assume deploying `amount` corresponds to increasing weight by a small fraction.
        # This is a simplification: we treat net liq as proportional to total_quantity.
        delta_weight = min(0.05, max(0.0, amount / (total_quantity + amount)))
        new_weight = min(1.0, current_weight + delta_weight)
        base_weight = max(0.0, 1.0 - delta_weight)

        # Approximate combined returns as convex combination of base portfolio and symbol.
        combined_returns: list[float] = []
        for b, s in zip(base_returns, sym_rets[-len(base_returns) :]):
            combined_returns.append(base_weight * b + new_weight * s)

        combined_vol = (
            statistics.pstdev(combined_returns)
            if len(combined_returns) > 1
            else base_vol
        )
        vol_change = combined_vol - base_vol

        suggestion_rows.append(
            InvestRow(
                symbol=symbol,
                avg_daily_return=avg_ret,
                volatility=sym_vol,
                combined_volatility=combined_vol,
                vol_change=vol_change,
            )
        )

    suggestion_rows.sort(key=lambda r: r.vol_change)
    return suggestion_rows


def filter_invest_rows_by_max_weight(
    rows: Sequence[InvestRow],
    snapshot: PortfolioSnapshot,
    provider: PriceProvider,
    amount: float,
    max_weights: Mapping[str, float],
    default_max_weight: float | None = None,
) -> list[InvestRow]:
    """
    Filter InvestRow suggestions based on per-symbol and default max weights.

    For each symbol with a configured max weight, approximate the pro-forma
    weight if the full `amount` were deployed into that symbol at the latest
    available price. Suggestions that would breach the max weight are removed.
    """
    if not rows or amount <= 0.0:
        return list(rows)

    today = date.today()
    start_price_window = date(today.year, today.month, max(1, today.day - 10))

    # Approximate current net-liq and per-symbol market value.
    last_prices: dict[str, float] = {}
    total_value = snapshot.cash
    for symbol, pos in snapshot.positions.items():
        ohlc = provider.get_ohlc(symbol, start_price_window, today)
        if not ohlc:
            continue
        last_close = ohlc[-1].close
        last_prices[symbol] = last_close
        total_value += pos.quantity * last_close

    if total_value <= 0.0:
        return list(rows)

    filtered: list[InvestRow] = []
    for row in rows:
        symbol = row.symbol
        max_weight = max_weights.get(symbol, default_max_weight)
        if max_weight is None:
            filtered.append(row)
            continue
        price = last_prices.get(symbol)
        if price is None:
            filtered.append(row)
            continue

        position = snapshot.positions.get(symbol)
        current_value = position.quantity * price if position is not None else 0.0
        new_total = total_value + amount
        if new_total <= 0.0:
            filtered.append(row)
            continue

        new_weight = (current_value + amount) / new_total
        if new_weight <= max_weight + 1e-9:
            filtered.append(row)

    return filtered



