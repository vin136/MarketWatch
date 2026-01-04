from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(slots=True)
class OHLC:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(slots=True)
class Dividend:
    date: date
    amount: float


@dataclass(slots=True)
class Split:
    date: date
    ratio: float


class PriceProvider(Protocol):
    def get_ohlc(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[OHLC]:
        ...

    def get_dividends(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[Dividend]:
        ...

    def get_splits(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[Split]:
        ...


