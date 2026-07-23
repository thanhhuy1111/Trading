# Pipeline Lineage & Correlation

## Causation Chain Tracing
The `PipelineLineageService` records explicit parent-child entity relationships:
```
MarketEvent
 └── FeatureSnapshot
      └── AgentSignal
           └── CriticDecision
                └── TradeIntent
                     └── ApprovedOrder
                          └── Fill
                               └── LedgerTransaction
                                    └── PortfolioSnapshot
```

Querying `GET /operations/pipeline/{correlation_id}` returns the complete execution lineage for audit and verification.
