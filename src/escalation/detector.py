"""Stuck-state detection for the replay engine."""


class StuckDetector:
    """Tracks URL history and flags when automation stops making progress."""

    def __init__(self, threshold: int = 3) -> None:
        self._threshold = threshold
        self._url_history: list[str] = []

    def is_stuck(self, current_url: str) -> bool:
        """Return True if the same URL has appeared too many consecutive times."""
        self._url_history.append(current_url)
        if len(self._url_history) < self._threshold:
            return False
        recent = self._url_history[-self._threshold:]
        return len(set(recent)) == 1

    def reset(self) -> None:
        self._url_history = []
