from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Iterator
import json

from marketwatch.core.events import Event

logger = logging.getLogger(__name__)


class LedgerParseError(Exception):
    """Raised when ledger parsing fails in strict mode."""

    pass


def read_events(path: Path, strict: bool = False) -> Iterator[Event]:
    """
    Read events from a JSONL ledger file.

    Args:
        path: Path to the ledger.jsonl file
        strict: If True, raise LedgerParseError on malformed JSON.
                If False, log warning and skip malformed lines.

    Yields:
        Event objects parsed from the ledger

    Raises:
        LedgerParseError: In strict mode, if a line cannot be parsed
    """
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, 1):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            try:
                data = json.loads(line_stripped)
            except json.JSONDecodeError as e:
                if strict:
                    raise LedgerParseError(
                        f"Malformed JSON at line {line_num}: {e}"
                    ) from e
                logger.warning(
                    f"Skipping malformed JSON at line {line_num} in {path}: {e}"
                )
                continue

            try:
                yield Event.from_dict(data)
            except (KeyError, ValueError, TypeError) as e:
                if strict:
                    raise LedgerParseError(
                        f"Invalid event data at line {line_num}: {e}"
                    ) from e
                logger.warning(
                    f"Skipping invalid event at line {line_num} in {path}: {e}"
                )
                continue


def append_events(path: Path, events: Iterable[Event]) -> None:
    """
    Append events to a JSONL ledger file.

    Each event is flushed after writing to ensure data integrity
    in case of process crash.

    Args:
        path: Path to the ledger.jsonl file
        events: Events to append
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for event in events:
            line = json.dumps(event.to_dict(), separators=(",", ":")) + "\n"
            fh.write(line)
            fh.flush()  # Ensure each event is written before continuing


