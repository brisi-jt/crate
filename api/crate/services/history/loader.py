"""Read a Spotify extended-history export from a drop directory (or one file).

The export unpacks to a set of ``Streaming_History_Audio_*.json`` files (plus
video/podcast/search files this import ignores). Point the loader at the
directory and it concatenates every audio file's records; point it at a single
file and it reads just that one.
"""

import json
from pathlib import Path
from typing import Any

# Only the audio streaming-history files carry music plays. Video and the other
# export files (SearchQueries, Follow, etc.) are skipped.
_AUDIO_PREFIX = "Streaming_History_Audio"


def load_export_records(path: Path) -> list[dict[str, Any]]:
    """All records from the audio history file(s) at ``path``.

    ``path`` may be a directory (every ``Streaming_History_Audio_*.json`` in it
    is read, sorted for determinism) or a single JSON file (read as-is).
    """
    if not path.exists():
        raise FileNotFoundError(f"no history export at {path}")

    if path.is_file():
        return _read_file(path)

    records: list[dict[str, Any]] = []
    files = sorted(
        p
        for p in path.iterdir()
        if p.is_file() and p.name.startswith(_AUDIO_PREFIX) and p.suffix == ".json"
    )
    for file in files:
        records.extend(_read_file(file))
    return records


def _read_file(file: Path) -> list[dict[str, Any]]:
    data = json.loads(file.read_text())
    if not isinstance(data, list):
        raise ValueError(f"{file.name}: expected a JSON array of records")
    return data
