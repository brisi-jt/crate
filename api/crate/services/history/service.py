"""Top-level import orchestration: load → parse → ingest.

Thin glue so the CLI script (and the API, if an upload endpoint is ever added)
share one code path. Keeps the script free of parsing/DB logic.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from crate.model.orm import User
from crate.services.history.ingest import IngestReport, ingest_history
from crate.services.history.loader import load_export_records
from crate.services.history.parser import ParsedHistory, parse_history_records


@dataclass
class ImportReport:
    """Everything one import pass touched, for CLI/API reporting."""

    records_read: int
    parsed: ParsedHistory
    ingest: IngestReport | None  # None on a dry run (nothing written)

    @property
    def dry_run(self) -> bool:
        return self.ingest is None


def import_export(
    session: Session, user: User, path: Path, *, dry_run: bool = False
) -> ImportReport:
    """Load the export at ``path``, parse it, and (unless dry-run) ingest it."""
    records = load_export_records(path)
    parsed = parse_history_records(records)
    ingest = None if dry_run else ingest_history(session, user, parsed)
    return ImportReport(records_read=len(records), parsed=parsed, ingest=ingest)
