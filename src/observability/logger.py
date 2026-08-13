"""Structured JSON logging for all automation runs."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredLogger:
    """Writes structured JSON log entries for every agent or replay action."""

    def __init__(self, run_dir: str, run_id: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self.run_dir / "run_log.json"
        self._entries: list[dict[str, Any]] = []

    def log(self, event: dict[str, Any]) -> None:
        """Append a structured log entry with a UTC timestamp."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            **event,
        }
        self._entries.append(entry)
        self._flush()

    def _flush(self) -> None:
        with open(self._log_path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, default=str)

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
