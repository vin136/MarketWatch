from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import List
import csv
import math

try:
    import yfinance as yf  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled at call time
    yf = None  # type: ignore[assignment]

from marketwatch.prices.base import Dividend, OHLC, PriceProvider, Split


class YahooPriceProvider(PriceProvider):
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else None

    def _cache_path(self, symbol: str, kind: str) -> Path | None:
        if self._cache_dir is None:
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{symbol}__{kind}.csv"
        return self._cache_dir / filename

    def _load_ohlc_from_cache(self, path: Path | None) -> list[OHLC] | None:
        if path is None or not path.exists():
            return None
        result: list[OHLC] = []
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    d = date.fromisoformat(str(row["date"]))
                    result.append(
                        OHLC(
                            date=d,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]) if row.get("volume") not in (None, "") else None,
                        )
                    )
                except Exception:  # noqa: BLE001
                    continue
        return result

    def _save_ohlc_to_cache(self, path: Path | None, values: list[OHLC]) -> None:
        if path is None:
            return
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "open", "high", "low", "close", "volume"])
            for item in values:
                writer.writerow(
                    [
                        item.date.isoformat(),
                        item.open,
                        item.high,
                        item.low,
                        item.close,
                        item.volume if item.volume is not None else "",
                    ]
                )

    def _load_dividends_from_cache(self, path: Path | None) -> list[Dividend] | None:
        if path is None or not path.exists():
            return None
        result: list[Dividend] = []
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    d = date.fromisoformat(str(row["date"]))
                    result.append(Dividend(date=d, amount=float(row["amount"])))
                except Exception:  # noqa: BLE001
                    continue
        return result

    def _save_dividends_to_cache(self, path: Path | None, values: list[Dividend]) -> None:
        if path is None:
            return
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "amount"])
            for item in values:
                writer.writerow([item.date.isoformat(), item.amount])

    def _load_splits_from_cache(self, path: Path | None) -> list[Split] | None:
        if path is None or not path.exists():
            return None
        result: list[Split] = []
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    d = date.fromisoformat(str(row["date"]))
                    result.append(Split(date=d, ratio=float(row["ratio"])))
                except Exception:  # noqa: BLE001
                    continue
        return result

    def _save_splits_to_cache(self, path: Path | None, values: list[Split]) -> None:
        if path is None:
            return
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "ratio"])
            for item in values:
                writer.writerow([item.date.isoformat(), item.ratio])

    def get_ohlc(self, symbol: str, start: date, end: date) -> List[OHLC]:
        if yf is None:
            msg = "yfinance is required to fetch OHLC data but is not installed."
            raise RuntimeError(msg)
        cache_path = self._cache_path(symbol, "ohlc")
        cached = self._load_ohlc_from_cache(cache_path) or []
        existing = {bar.date: bar for bar in cached}

        # Determine which date ranges (if any) are missing from the cache.
        missing_ranges: list[tuple[date, date]] = []
        if existing:
            known_dates = sorted(existing.keys())
            first_known, last_known = known_dates[0], known_dates[-1]
            if start < first_known:
                missing_ranges.append((start, first_known))
            if end > last_known:
                missing_ranges.append((last_known, end))
        else:
            missing_ranges.append((start, end))

        if missing_ranges:
            ticker = yf.Ticker(symbol)
            for s, e in missing_ranges:
                if s >= e:
                    continue
                hist = ticker.history(start=s, end=e, auto_adjust=False)
                for idx, row in hist.iterrows():
                    ts = idx.to_pydatetime()
                    bar_date = ts.date() if hasattr(ts, "date") else ts
                    new_bar = OHLC(
                        date=bar_date,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]) if "Volume" in row else None,
                    )
                    # Basic sanity checks: finite values only.
                    for value in (
                        new_bar.open,
                        new_bar.high,
                        new_bar.low,
                        new_bar.close,
                    ):
                        if not math.isfinite(value):
                            msg = (
                                f"Non-finite OHLC value for {symbol} on "
                                f"{new_bar.date}: {new_bar}"
                            )
                            raise RuntimeError(msg)

                    # If we already have a cached bar for this date, ensure it is
                    # consistent. If not, fail loudly so the user can inspect
                    # their cache.
                    existing_bar = existing.get(new_bar.date)
                    if existing_bar is not None:
                        if any(
                            abs(a - b) > 1e-6
                            for a, b in [
                                (existing_bar.open, new_bar.open),
                                (existing_bar.high, new_bar.high),
                                (existing_bar.low, new_bar.low),
                                (existing_bar.close, new_bar.close),
                            ]
                        ):
                            msg = (
                                f"Inconsistent cached OHLC for {symbol} on "
                                f"{new_bar.date}: cached={existing_bar}, "
                                f"fetched={new_bar}"
                            )
                            raise RuntimeError(msg)

                    existing[new_bar.date] = new_bar

        merged = sorted(existing.values(), key=lambda b: b.date)
        self._save_ohlc_to_cache(cache_path, merged)
        return [b for b in merged if start <= b.date <= end]

    def get_dividends(self, symbol: str, start: date, end: date) -> list[Dividend]:
        if yf is None:
            msg = "yfinance is required to fetch dividends but is not installed."
            raise RuntimeError(msg)
        cache_path = self._cache_path(symbol, "dividends")
        cached = self._load_dividends_from_cache(cache_path) or []
        existing = {d.date: d for d in cached}

        ticker = yf.Ticker(symbol)
        div = ticker.dividends
        for idx, value in div.items():
            ts: datetime = idx.to_pydatetime()
            d = ts.date()
            if start <= d <= end:
                existing[d] = Dividend(date=d, amount=float(value))

        merged = sorted(existing.values(), key=lambda dv: dv.date)
        self._save_dividends_to_cache(cache_path, merged)
        return [dv for dv in merged if start <= dv.date <= end]

    def get_splits(self, symbol: str, start: date, end: date) -> list[Split]:
        if yf is None:
            msg = "yfinance is required to fetch splits but is not installed."
            raise RuntimeError(msg)
        cache_path = self._cache_path(symbol, "splits")
        cached = self._load_splits_from_cache(cache_path) or []
        existing = {s.date: s for s in cached}

        ticker = yf.Ticker(symbol)
        splits = ticker.splits
        for idx, value in splits.items():
            ts: datetime = idx.to_pydatetime()
            d = ts.date()
            if start <= d <= end:
                existing[d] = Split(date=d, ratio=float(value))

        merged = sorted(existing.values(), key=lambda sp: sp.date)
        self._save_splits_to_cache(cache_path, merged)
        return [sp for sp in merged if start <= sp.date <= end]


