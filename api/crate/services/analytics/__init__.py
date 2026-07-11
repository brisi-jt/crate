"""Analytics engine: pure computations over the local database.

Everything in this package works in percentile space — feature values ranked
against the library's own distribution — because the underlying values are
Essentia-derived and their absolute scales are not comparable to Spotify's.
"""
