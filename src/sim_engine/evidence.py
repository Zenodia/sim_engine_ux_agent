import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Journal:
    """Append-only application evidence; this is not a production memory database."""

    def __init__(self, path: Path, **context: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.context = context
        self.sequence = 0

    def emit(self, kind: str, **data: Any) -> None:
        self.sequence += 1
        event = {
            "event_schema": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": self.sequence,
            **self.context,
            "kind": kind,
            "data": data,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

