from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator
import json

from marketwatch.core.events import Event


def read_events(path: Path) -> Iterator[Event]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            data = json.loads(line_stripped)
            yield Event.from_dict(data)


def append_events(path: Path, events: Iterable[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for event in events:
            json.dump(event.to_dict(), fh, separators=(",", ":"))
            fh.write("\n")


