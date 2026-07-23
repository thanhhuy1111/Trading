class RecommendationError(Exception):
    """Base exception for the recommendation domain."""


class MarketDataUnavailableError(RecommendationError):
    """Raised when market data cannot be fetched for a requested symbol/timeframe."""


class ProposalNotFoundError(RecommendationError):
    """Raised when analyze_trade_proposal / validate_trade_proposal cannot locate a proposal_id."""


class InvalidCandidateError(RecommendationError):
    """Raised when a TradeCandidate fails structural invariants before proposal building."""
