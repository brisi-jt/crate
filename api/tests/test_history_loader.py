"""History file loader — reads Streaming_History_Audio_*.json from a drop-dir."""

import json
from pathlib import Path

import pytest

from crate.services.history.loader import load_export_records

pytestmark = pytest.mark.unit


def _write(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records))


def test_reads_audio_history_files_from_a_directory(tmp_path: Path) -> None:
    _write(tmp_path / "Streaming_History_Audio_2021_1.json", [{"ts": "a"}])
    _write(tmp_path / "Streaming_History_Audio_2021_2.json", [{"ts": "b"}, {"ts": "c"}])

    records = load_export_records(tmp_path)

    assert len(records) == 3
    assert {r["ts"] for r in records} == {"a", "b", "c"}


def test_ignores_video_and_unrelated_files(tmp_path: Path) -> None:
    _write(tmp_path / "Streaming_History_Audio_2021.json", [{"ts": "audio"}])
    _write(tmp_path / "Streaming_History_Video_2021.json", [{"ts": "video"}])
    _write(tmp_path / "SearchQueries.json", [{"ts": "search"}])
    (tmp_path / "notes.txt").write_text("hello")

    records = load_export_records(tmp_path)

    assert [r["ts"] for r in records] == ["audio"]


def test_accepts_a_single_file_path(tmp_path: Path) -> None:
    file = tmp_path / "Streaming_History_Audio_full.json"
    _write(file, [{"ts": "x"}])

    assert load_export_records(file) == [{"ts": "x"}]


def test_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_export_records(tmp_path / "nope")
