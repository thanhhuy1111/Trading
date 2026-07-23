"""Shared enums for the architecture-complete Trading Advisor domain model.

Explicit enums, not free-form strings, for every state that governs a downstream decision —
per the task's "use explicit enums rather than free-form strings for critical states."
"""

from enum import Enum

# Six independent readiness axes (Section 3). Architecture completion must never be confused
# with strategy approval — that's exactly why these are separate enums on a separate entity
# (ReadinessStatus, see entities.py), not one combined "is it ready" boolean.


class ArchitectureReadiness(str, Enum):
    NOT_READY = "NOT_READY"
    PARTIAL = "PARTIAL"
    READY = "READY"


class StrategyReadiness(str, Enum):
    NOT_READY = "NOT_READY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    ASSET_SPECIFIC_APPROVED = "ASSET_SPECIFIC_APPROVED"
    UNIVERSAL_APPROVED = "UNIVERSAL_APPROVED"


class ModelReadiness(str, Enum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BASELINE = "BASELINE"          # pass-through / heuristic, not a trained model
    RESEARCH_ONLY = "RESEARCH_ONLY"  # a trained model exists but is not approved
    APPROVED = "APPROVED"


class EvidenceReadiness(str, Enum):
    EMPTY_REGISTRY = "EMPTY_REGISTRY"
    NO_APPROVED_STRATEGY = "NO_APPROVED_STRATEGY"
    ASSET_SPECIFIC_EVIDENCE = "ASSET_SPECIFIC_EVIDENCE"
    UNIVERSAL_EVIDENCE = "UNIVERSAL_EVIDENCE"


class ShadowReadiness(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    ACTIVE = "ACTIVE"


class LiveReadiness(str, Enum):
    DISABLED = "DISABLED"
    # No other values are implemented. Live trading enablement is explicitly out of scope for
    # every checkpoint so far and remains a manual, separate, human decision outside this
    # codebase's automated pipeline (Master Plan principle 1: "Live trading remains disabled").


class DatasetQualityLevel(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


class CandidateStatus(str, Enum):
    """Mirrors packages/candidates/models.py: CandidateStatus — re-declared here only where
    a domain-level dependency needs it without importing the whole candidates package; the
    canonical source of truth stays packages/candidates/models.py."""
    PROPOSED = "PROPOSED"
    RISK_REJECTED = "RISK_REJECTED"
    APPROVED = "APPROVED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


class EvidenceLookupResult(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    STALE = "STALE"
    DISABLED = "DISABLED"


class RegistryEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISABLED = "DISABLED"
    REJECTED = "REJECTED"


class ModelType(str, Enum):
    RULE_BASED = "RULE_BASED"
    PASS_THROUGH = "PASS_THROUGH"
    LOGISTIC_REGRESSION = "LOGISTIC_REGRESSION"
    TREE_MODEL = "TREE_MODEL"


class MetaLabelDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER_TO_EXISTING_RULES = "DEFER_TO_EXISTING_RULES"


class MarketContextStatus(str, Enum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"


class RankingStatus(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    EVIDENCE_BACKED = "EVIDENCE_BACKED"


class PortfolioRiskDecisionType(str, Enum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    REJECT = "REJECT"
    HALT = "HALT"


class ApplicationResultState(str, Enum):
    APPROVED_PROPOSAL = "APPROVED_PROPOSAL"
    RESEARCH_PROPOSAL = "RESEARCH_PROPOSAL"
    NO_TRADE = "NO_TRADE"
    NO_CANDIDATE = "NO_CANDIDATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    STRATEGY_NOT_APPROVED = "STRATEGY_NOT_APPROVED"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    STALE_DATA = "STALE_DATA"
    DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    SYSTEM_DEGRADED = "SYSTEM_DEGRADED"


class ShadowProposalKind(str, Enum):
    APPROVED_SHADOW = "APPROVED_SHADOW"
    RESEARCH_SHADOW = "RESEARCH_SHADOW"


class ShadowOutcomeStatus(str, Enum):
    PENDING = "PENDING"
    BARRIER_EXIT = "BARRIER_EXIT"
    TIMEOUT_EXIT = "TIMEOUT_EXIT"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class DriftSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class LLMAgentStatus(str, Enum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    OK = "OK"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
