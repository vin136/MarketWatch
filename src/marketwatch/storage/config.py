from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass(slots=True)
class SymbolConfig:
    buy_target: float | None = None
    sell_target: float | None = None
    intrinsic_value: float | None = None
    max_weight: float | None = None
    note: str | None = None


@dataclass(slots=True)
class Config:
    name: str
    base_currency: str = "USD"
    baseline_symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    fd_rate: float = 0.05
    default_max_weight: float = 0.05
    whatsup_lookback_days: int = 252
    invest_lookback_years: int = 5
    symbols: dict[str, SymbolConfig] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_currency": self.base_currency,
            "baseline_symbols": list(self.baseline_symbols),
            "fd_rate": self.fd_rate,
            "default_max_weight": self.default_max_weight,
            "whatsup_lookback_days": self.whatsup_lookback_days,
            "invest_lookback_years": self.invest_lookback_years,
            "symbols": {
                sym: {
                    "buy_target": cfg.buy_target,
                    "sell_target": cfg.sell_target,
                    "intrinsic_value": cfg.intrinsic_value,
                    "max_weight": cfg.max_weight,
                    "note": cfg.note,
                }
                for sym, cfg in self.symbols.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        symbols_raw = data.get("symbols", {}) or {}
        symbols: dict[str, SymbolConfig] = {}
        for sym, cfg_data in symbols_raw.items():
            symbols[sym] = SymbolConfig(
                buy_target=cfg_data.get("buy_target"),
                sell_target=cfg_data.get("sell_target"),
                intrinsic_value=cfg_data.get("intrinsic_value"),
                max_weight=cfg_data.get("max_weight"),
                note=cfg_data.get("note"),
            )
        return cls(
            name=data["name"],
            base_currency=data.get("base_currency", "USD"),
            baseline_symbols=list(data.get("baseline_symbols", ["SPY", "QQQ"])),
            fd_rate=float(data.get("fd_rate", 0.05)),
            default_max_weight=float(data.get("default_max_weight", 0.05)),
            whatsup_lookback_days=int(data.get("whatsup_lookback_days", 252)),
            invest_lookback_years=int(data.get("invest_lookback_years", 5)),
            symbols=symbols,
        )


def load_config(path: Path) -> Config | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Config.from_dict(data)


def save_config(path: Path, config: Config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(config.to_dict(), fh, indent=2, sort_keys=True)


