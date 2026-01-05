from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Iterable

from marketwatch.core.events import Event, apply_corrections

logger = logging.getLogger(__name__)


def _round_money(value: float) -> float:
    """Round to 4 decimal places for financial calculations."""
    return round(value, 4)


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float = 0.0
    total_cost: float = 0.0

    @property
    def cost_basis(self) -> float | None:
        if self.quantity <= 0.0:
            return None
        return _round_money(self.total_cost / self.quantity)


@dataclass(slots=True)
class PortfolioSnapshot:
    positions: dict[str, Position]
    cash: float


def build_snapshot(events: Iterable[Event]) -> PortfolioSnapshot:
    """
    Build a portfolio snapshot by replaying events.

    Applies precision handling for financial calculations and validates
    event data, skipping invalid events with warnings.

    Args:
        events: Iterable of events to replay

    Returns:
        PortfolioSnapshot with current positions and cash balance
    """
    effective_events = apply_corrections(list(events))

    positions: dict[str, Position] = {}
    cash = 0.0

    for event in effective_events:
        if event.type == "cash_movement":
            amount = float(event.payload.get("amount", 0.0) or 0.0)
            if not math.isfinite(amount):
                logger.warning(f"Skipping event {event.id}: invalid amount {amount}")
                continue
            cash = _round_money(cash + amount)

        elif event.type == "dividend":
            # Handle dividend events - add to cash
            amount = float(event.payload.get("dividend_amount", 0.0) or 0.0)
            if not math.isfinite(amount):
                logger.warning(f"Skipping event {event.id}: invalid dividend_amount {amount}")
                continue
            cash = _round_money(cash + amount)

        elif event.type == "generic_trade":
            pnl = float(event.payload.get("pnl", 0.0) or 0.0)
            if not math.isfinite(pnl):
                logger.warning(f"Skipping event {event.id}: invalid pnl {pnl}")
                continue
            cash = _round_money(cash + pnl)

        elif event.type in ("init_position", "trade_add"):
            symbol = event.payload.get("symbol")
            if not symbol:
                logger.warning(f"Skipping event {event.id}: missing symbol")
                continue
            symbol_str = str(symbol)
            position = positions.get(symbol_str)
            if position is None:
                position = Position(symbol=symbol_str)
                positions[symbol_str] = position

            if event.type == "init_position":
                quantity = float(event.payload.get("quantity", 0.0) or 0.0)
                cost_price = float(event.payload.get("cost_price", 0.0) or 0.0)

                # Validate inputs
                if not math.isfinite(quantity) or quantity < 0:
                    logger.warning(f"Skipping event {event.id}: invalid quantity {quantity}")
                    continue
                if not math.isfinite(cost_price) or cost_price < 0:
                    logger.warning(f"Skipping event {event.id}: invalid cost_price {cost_price}")
                    continue

                position.quantity = _round_money(position.quantity + quantity)
                position.total_cost = _round_money(position.total_cost + quantity * cost_price)
            else:
                delta = float(event.payload.get("quantity_delta", 0.0) or 0.0)
                price = float(event.payload.get("price", 0.0) or 0.0)

                # Validate inputs (delta can be negative for sells)
                if not math.isfinite(delta):
                    logger.warning(f"Skipping event {event.id}: invalid quantity_delta {delta}")
                    continue
                if not math.isfinite(price) or price < 0:
                    logger.warning(f"Skipping event {event.id}: invalid price {price}")
                    continue

                if delta >= 0.0:
                    # Buy
                    position.quantity = _round_money(position.quantity + delta)
                    position.total_cost = _round_money(position.total_cost + delta * price)
                else:
                    # Sell - remove at average cost basis
                    remove_qty = -delta
                    if position.quantity > 0.0:
                        avg_cost = position.total_cost / position.quantity
                        # Ensure we don't remove more than we have
                        actual_remove = min(remove_qty, position.quantity)
                        position.quantity = _round_money(position.quantity - actual_remove)
                        position.total_cost = _round_money(position.total_cost - actual_remove * avg_cost)

        # config_change and correction events are ignored for snapshot

    # Drop fully closed positions (threshold for floating point)
    positions = {
        sym: pos for sym, pos in positions.items() if abs(pos.quantity) > 1e-9
    }

    return PortfolioSnapshot(positions=positions, cash=cash)


