"""Save and load CapabilityArtifact objects to/from JSON files."""

import json
from pathlib import Path

from src.artifact.schema import CapabilityArtifact


class ArtifactStore:
    """Persists capability artifacts as JSON files on the local filesystem."""

    def save(self, artifact: CapabilityArtifact, path: str) -> str:
        """Serialise the artifact to JSON and write it to disk."""
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(artifact.model_dump(mode="json"), f, indent=2, default=str)
        return str(dest)

    def load(self, path: str) -> CapabilityArtifact:
        """Deserialise a capability artifact from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CapabilityArtifact.model_validate(data)
