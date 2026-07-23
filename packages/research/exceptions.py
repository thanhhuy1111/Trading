class ResearchError(Exception):
    """Base exception for the alpha research pipeline."""


class DatasetValidationError(ResearchError):
    """Raised when raw candles fail structural validation (duplicates, gaps, bad OHLC,
    negative volume, out-of-order, future timestamps, unsupported symbol/timeframe)."""


class InsufficientDataError(ResearchError):
    """Raised when there are too few candles/observations to build a dataset, split, or
    evaluation window meaningfully."""


class LeakageError(ResearchError):
    """Raised when a feature or split is detected to use information from after its
    as-of time (future high/low/close/return, or a label field)."""


class ArtifactNotFoundError(ResearchError):
    """Raised when a dataset/model/evaluation/evidence artifact cannot be found by ID."""


class ChecksumMismatchError(ResearchError):
    """Raised when a loaded artifact's recomputed checksum does not match its recorded
    checksum -- the artifact on disk has been tampered with or corrupted."""
