class InsufficientDataError(ValueError):
    """Raised when a statistic is asked to compute over too little real data rather than
    silently returning a fabricated or degenerate value."""
