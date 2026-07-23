class Topics:
    """Centralized Event Bus Topic Registry."""
    SYSTEM_EVENTS = "trading.system.events.v1"
    CONFIG_EVENTS = "trading.config.events.v1"
    MARKET_EVENTS = "trading.market.events.v1"
    INTELLIGENCE_EVENTS = "trading.intelligence.events.v1"
    RISK_EVENTS = "trading.risk.events.v1"
    EXECUTION_EVENTS = "trading.execution.events.v1"
    AUDIT_EVENTS = "trading.audit.events.v1"
    DEAD_LETTER = "trading.dead-letter.v1"

    ALL_TOPICS = [
        SYSTEM_EVENTS,
        CONFIG_EVENTS,
        MARKET_EVENTS,
        INTELLIGENCE_EVENTS,
        RISK_EVENTS,
        EXECUTION_EVENTS,
        AUDIT_EVENTS,
        DEAD_LETTER,
    ]
