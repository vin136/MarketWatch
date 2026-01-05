from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypedDict, Iterable, List, get_args

EventType = Literal[
    "init_position",
    "trade_add",
    "cash_movement",
    "generic_trade",
    "config_change",
    "correction",
    "dividend",
]

# Valid event types for validation
VALID_EVENT_TYPES = get_args(EventType)


class EventValidationError(ValueError):
    """Raised when event data fails validation."""

    pass


class EventPayload(TypedDict, total=False):
    symbol: str
    quantity: float
    cost_price: float
    quantity_delta: float
    price: float
    amount: float
    cash_needed: float
    duration: str
    pnl: float
    buy_target: float | None
    sell_target: float | None
    intrinsic_value: float | None
    max_weight: float | None
    fd_rate: float | None
    target_event_id: str
    correction_type: Literal["replace", "invalidate"]
    new_payload: dict[str, Any] | None
    # Dividend fields
    dividend_amount: float
    dividend_per_share: float


@dataclass(slots=True)
class Event:
    id: str
    timestamp: datetime
    type: EventType
    payload: EventPayload
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type,
            "payload": dict(self.payload),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        """
        Parse an Event from a dictionary.

        Validates required fields and raises EventValidationError if invalid.

        Args:
            data: Dictionary containing event data

        Returns:
            Event instance

        Raises:
            EventValidationError: If required fields are missing or invalid
        """
        # Validate required fields
        for field in ("id", "timestamp", "type"):
            if field not in data:
                raise EventValidationError(f"Missing required field: {field}")

        # Validate event type
        event_type = data["type"]
        if event_type not in VALID_EVENT_TYPES:
            raise EventValidationError(
                f"Invalid event type: {event_type}. "
                f"Must be one of: {', '.join(VALID_EVENT_TYPES)}"
            )

        # Parse and validate timestamp
        timestamp_str = data["timestamp"]
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError) as e:
            raise EventValidationError(
                f"Invalid timestamp format: {timestamp_str}. Expected ISO format."
            ) from e

        payload_raw = data.get("payload", {}) or {}
        payload: EventPayload = EventPayload(**payload_raw)

        return cls(
            id=str(data["id"]),
            timestamp=timestamp,
            type=event_type,
            payload=payload,
            note=data.get("note"),
        )


def apply_corrections(events: Iterable[Event]) -> list[Event]:
    base_events: list[Event] = []
    corrections: dict[str, EventPayload] = {}

    for event in events:
        if event.type == "correction":
            target_id = event.payload.get("target_event_id")
            correction_type = event.payload.get("correction_type")
            if not target_id or not correction_type:
                continue
            if correction_type == "invalidate":
                corrections[str(target_id)] = EventPayload(
                    target_event_id=str(target_id),
                    correction_type="invalidate",
                    new_payload=None,
                )
            elif correction_type == "replace":
                new_payload = event.payload.get("new_payload") or {}
                corrections[str(target_id)] = EventPayload(
                    target_event_id=str(target_id),
                    correction_type="replace",
                    new_payload=new_payload,
                )
        else:
            base_events.append(event)

    effective: list[Event] = []
    for event in base_events:
        corr = corrections.get(event.id)
        if corr is None:
            effective.append(event)
            continue
        ctype = corr.get("correction_type")
        if ctype == "invalidate":
            continue
        if ctype == "replace":
            new_payload_raw = corr.get("new_payload") or {}
            new_payload: EventPayload = EventPayload(**new_payload_raw)
            effective.append(
                Event(
                    id=event.id,
                    timestamp=event.timestamp,
                    type=event.type,
                    payload=new_payload,
                    note=event.note,
                )
            )
        else:
            effective.append(event)

    return effective



