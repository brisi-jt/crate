"""Insight pins - field-manual annotations anchored to canvas surfaces.

A pin is a short readout attached to a node/region/artist on one of the three
canvas surfaces (graph, field, galaxy). Pins are deterministic: for each
surface a fixed salience score ranks candidates and the top 2-4 are kept, so
the same library state always produces the same pins (no randomness).

Each pin carries a stable dismissible_id (surface + anchor + metric) so the web
can remember dismissals across reloads.
"""

from typing import Any

from crate.services.insights.metrics import FINGERPRINT_FEATURES

# Pins kept per surface - 2 minimum for texture, 4 maximum to avoid clutter.
MIN_PINS = 2
MAX_PINS = 4


def _pin(surface: str, anchor: str, metric_ref: str, text: str, salience: float) -> dict[str, Any]:
    return {
        "anchor": anchor,
        "metric_ref": metric_ref,
        "line": text,
        "dismissible_id": f"{surface}:{anchor}:{metric_ref}",
        "salience": round(salience, 4),
    }


def _rank(pins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Top MAX_PINS by salience, ties broken by dismissible_id for determinism."""
    ordered = sorted(pins, key=lambda pin: (-pin["salience"], pin["dismissible_id"]))
    return ordered[:MAX_PINS]


def field_pins(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pins for the track field (sound map).

    Salience favours the strongest fingerprint axes and the largest mood
    quadrant - the field's most legible facts.
    """
    identity = payload["taste_identity"]
    sonic = payload["sonic_signatures"]
    pins: list[dict[str, Any]] = []

    fingerprint = {entry["feature"]: entry["percentile"] for entry in identity["fingerprint"]}
    for feature in FINGERPRINT_FEATURES:
        value = fingerprint.get(feature)
        if value is None:
            continue
        # Salience = distance from the median - extreme axes are the story.
        salience = abs(value - 0.5)
        if salience < 0.15:
            continue
        band = "high" if value >= 0.5 else "low"
        pins.append(
            _pin(
                "field",
                anchor=feature,
                metric_ref="fingerprint",
                text=f"Your library reads {band}-{feature} (P{round(value * 100)}).",
                salience=salience,
            )
        )

    mood = sonic["mood"]
    if mood["total"]:
        top_quadrant = max(mood["shares"].items(), key=lambda item: (item[1], item[0]))
        label = top_quadrant[0].replace("_", "-")
        pins.append(
            _pin(
                "field",
                anchor=f"quadrant:{top_quadrant[0]}",
                metric_ref="mood",
                text=(
                    f"{round(top_quadrant[1] * 100)}% of your library sits in the {label} quadrant."
                ),
                salience=top_quadrant[1],
            )
        )
    return _rank(pins)


def galaxy_pins(galaxy: dict[str, Any]) -> list[dict[str, Any]]:
    """Pins for the artist galaxy - bridge artists and deepest catalogs.

    galaxy is the artist-galaxy payload (nodes with track/playlist counts).
    Salience favours artists spanning many playlists (bridges) and the deepest
    single-artist catalogs.
    """
    pins: list[dict[str, Any]] = []
    nodes = galaxy.get("nodes", [])

    bridges = sorted(nodes, key=lambda node: (-node.get("playlist_count", 0), node.get("id", "")))
    for node in bridges[:2]:
        if node.get("playlist_count", 0) < 2:
            continue
        pins.append(
            _pin(
                "galaxy",
                anchor=node["id"],
                metric_ref="playlist_count",
                text=f"{node['name']} bridges {node['playlist_count']} of your playlists.",
                salience=node["playlist_count"] / max(1, len(nodes)),
            )
        )

    catalogs = sorted(nodes, key=lambda node: (-node.get("track_count", 0), node.get("id", "")))
    for node in catalogs[:2]:
        if node.get("track_count", 0) < 3:
            continue
        pins.append(
            _pin(
                "galaxy",
                anchor=node["id"],
                metric_ref="track_count",
                text=f"You hold {node['track_count']} tracks from {node['name']}.",
                salience=min(1.0, node["track_count"] / 20.0),
            )
        )
    return _rank(pins)


def graph_pins(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pins for the playlist graph - dormant playlists and genre-family notes.

    Salience favours the most dormant playlists and the rarest genre family in
    the library (the graph's identity subset).
    """
    archaeology = payload["archaeology"]
    identity = payload["taste_identity"]
    pins: list[dict[str, Any]] = []

    for entry in archaeology["abandoned_playlists"][:2]:
        pins.append(
            _pin(
                "graph",
                anchor=f"playlist:{entry['playlist_id']}",
                metric_ref="dormancy",
                text=f"{entry['name']} has sat untouched for {entry['months_dormant']} months.",
                salience=min(1.0, entry["months_dormant"] / 24.0),
            )
        )

    rarest = identity["genre_rarity"]["rarest"]
    for entry in rarest[:2]:
        pins.append(
            _pin(
                "graph",
                anchor=f"genre:{entry['genre']}",
                metric_ref="rarity",
                text=(
                    f"{entry['genre']} is one of your rarest genres (rarity {entry['rarity']:.2f})."
                ),
                salience=entry["rarity"],
            )
        )
    return _rank(pins)


def compute_pins_payload(
    payload: dict[str, Any], galaxy: dict[str, Any], surface: str
) -> dict[str, Any]:
    """Pins for one surface, drawn deterministically from the insights payload.

    surface is one of graph / field / galaxy. Returns {"surface", "pins"};
    pins is 0..MAX_PINS entries (fewer when the data is thin).
    """
    if surface == "field":
        pins = field_pins(payload)
    elif surface == "galaxy":
        pins = galaxy_pins(galaxy)
    else:  # graph
        pins = graph_pins(payload)
    return {"surface": surface, "pins": pins}
