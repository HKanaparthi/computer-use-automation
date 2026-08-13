"""Evidence collection: gathers and organizes run artifacts for review."""

import json
from pathlib import Path
from typing import Any


class EvidenceCollector:
    """Organizes all outputs from a single run into a structured directory."""

    def __init__(self, run_dir: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def save_artifact(self, artifact_data: dict[str, Any], filename: str = "artifact.json") -> str:
        """Write the capability artifact JSON to the run directory."""
        path = self.run_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(artifact_data, f, indent=2, default=str)
        return str(path)

    def save_error_report(self, error_data: dict[str, Any]) -> str:
        """Write an error report for failed replay runs."""
        path = self.run_dir / "error_report.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2, default=str)
        return str(path)

    def list_screenshots(self) -> list[str]:
        """Return paths to all screenshots captured in this run."""
        screenshots_dir = self.run_dir / "screenshots"
        if not screenshots_dir.exists():
            return []
        return sorted(str(p) for p in screenshots_dir.glob("*.png"))
