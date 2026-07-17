"""Typed evidence models for triage suggestions.

Each destination suggestion carries one Evidence row per EvidenceKind, each
separately labeled with a human-readable ``summary`` and a structured
``detail`` — never a single blended score, and never a raw dict.
"""

from typing import Any

from pydantic import BaseModel, Field

from crate.model.enums import EvidenceKind


class Evidence(BaseModel):
    """One named signal behind a destination suggestion."""

    kind: EvidenceKind
    # 0..1 strength of this one signal, kept separate from the others so the
    # UI shows four labeled rows rather than a blended number.
    score: float = Field(ge=0.0, le=1.0)
    summary: str = Field(
        description="Human-readable one-liner, e.g. '3 tracks by this artist here'."
    )
    detail: dict[str, Any] = Field(default_factory=dict)


class DestinationSuggestion(BaseModel):
    """One candidate destination playlist for the filed track."""

    playlist_id: int
    name: str
    # Combined rank score — for ordering only; the four evidence rows carry the
    # explanation. Never presented as "the" score in place of the evidence.
    rank: float = Field(ge=0.0, le=1.0)
    already_in: bool = Field(
        description="True when the track is already in this playlist (greyed, still selectable)."
    )
    evidence: list[Evidence]
