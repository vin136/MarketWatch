from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from marketwatch.core.events import Event, apply_corrections


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float = 0.0
    total_cost: float = 0.0

    @property
    def cost_basis(self) -> float | None:
        if self.quantity <= 0.0:
            return None
        return self.total_cost / self.quantity


@dataclass(slots=True)
class PortfolioSnapshot:
    positions: dict[str, Position]
    cash: float


def build_snapshot(events: Iterable[Event]) -> PortfolioSnapshot:
    effective_events = apply_corrections(list(events))

    positions: dict[str, Position] = {}
    cash = 0.0

    for event in effective_events:
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
            symbol_str = str(symbol)
            position = positions.get(symbol_str)
            if position is None:
                position = Position(symbol=symbol_str)
                positions[symbol_str] = position

            if event.type == "init_position":
                quantity = float(event.payload.get("quantity", 0.0) or 0.0)
                cost_price = float(event.payload.get("cost_price", 0.0) or 0.0)
                position.quantity += quantity
                position.total_cost += quantity * cost_price
            else:
                delta = float(event.payload.get("quantity_delta", 0.0) or 0.0)
                price = float(event.payload.get("price", 0.0) or 0.0)
                if delta >= 0.0:
                    position.quantity += delta
                    position.total_cost += delta * price
                else:
                    # For sells, keep average cost basis and ignore realized PnL for now.
                    remove_qty = -delta
                    if position.quantity > 0.0:
                        avg_cost = position.total_cost / position.quantity
                        position.quantity -= remove_qty
                        position.total_cost -= min(remove_qty, position.quantity + remove_qty) * avg_cost

        # config_change and correction events are ignored for snapshot v1

    # Drop fully closed positions
    positions = {
        sym: pos for sym, pos in positions.items() if abs(pos.quantity) > 0.0
    }

    return PortfolioSnapshot(positions=positions, cash=cash)


