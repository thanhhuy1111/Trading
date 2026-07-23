# Event Catalog Specification

## Overview
This catalog specifies all domain event schemas registered in `packages/events/catalog.py`.
There are **32 registered domain event schemas** (spanning System, Configuration, Market Data, Intelligence, Risk, and Execution categories).

*Note on discrepancy in preliminary summary report*: The initial summary report condensed the catalog into 14 high-level event category samples for overview purposes, whereas `packages/events/catalog.py` contains all 32 granular domain event payload models registered with `EventRegistry`.

## Full Domain Event Catalog

| Event Type | Category | Schema Version | Payload Model | Topic | Expected Producer | Expected Consumer |
|---|---|---|---|---|---|---|
| `system.started` | System | 1 | `SystemStartedPayload` | `trading.system.events.v1` | System/API Engine | All Services |
| `system.stopped` | System | 1 | `SystemStoppedPayload` | `trading.system.events.v1` | System/API Engine | All Services |
| `system.soft_stop_requested` | System | 1 | `SystemSoftStopRequestedPayload` | `trading.system.events.v1` | Risk Governor / API | Risk Governor / Execution Engine |
| `system.hard_stop_requested` | System | 1 | `SystemHardStopRequestedPayload` | `trading.system.events.v1` | Risk Governor / API | Execution Engine |
| `system.health_changed` | System | 1 | `SystemHealthChangedPayload` | `trading.system.events.v1` | Health Monitor | Observability Engine |
| `system.incident_created` | System | 1 | `SystemIncidentCreatedPayload` | `trading.system.events.v1` | Incident Guardian | Observability / Dashboard |
| `system.incident_acknowledged` | System | 1 | `SystemIncidentAcknowledgedPayload` | `trading.system.events.v1` | Operator / API | Dashboard |
| `config.created` | Config | 1 | `ConfigCreatedPayload` | `trading.config.events.v1` | Config Manager | Audit Log |
| `config.updated` | Config | 1 | `ConfigUpdatedPayload` | `trading.config.events.v1` | Config Manager | Audit Log / Services |
| `config.activated` | Config | 1 | `ConfigActivatedPayload` | `trading.config.events.v1` | Config Manager | All Subsystem Engines |
| `config.deactivated` | Config | 1 | `ConfigDeactivatedPayload` | `trading.config.events.v1` | Config Manager | Audit Log |
| `risk_policy.created` | Config | 1 | `RiskPolicyCreatedPayload` | `trading.config.events.v1` | Config Manager | Risk Governor |
| `risk_policy.updated` | Config | 1 | `RiskPolicyUpdatedPayload` | `trading.config.events.v1` | Config Manager | Risk Governor |
| `risk_policy.activated` | Config | 1 | `RiskPolicyActivatedPayload` | `trading.config.events.v1` | Config Manager | Risk Governor |
| `market.tick_received` | Market | 1 | `MarketTickReceivedPayload` | `trading.market.events.v1` | Market Data Collector | Intelligence Agents |
| `market.candle_closed` | Market | 1 | `MarketCandleClosedPayload` | `trading.market.events.v1` | Market Data Collector | Intelligence Agents |
| `market.order_book_updated` | Market | 1 | `MarketOrderBookUpdatedPayload` | `trading.market.events.v1` | Market Data Collector | Intelligence Agents |
| `market.data_quality_changed` | Market | 1 | `MarketDataQualityChangedPayload` | `trading.market.events.v1` | Data Guardian | Risk Governor |
| `features.snapshot_created` | Intelligence | 1 | `FeaturesSnapshotCreatedPayload` | `trading.intelligence.events.v1` | Feature Store | Strategy Agents |
| `agent.signal_created` | Intelligence | 1 | `AgentSignalCreatedPayload` | `trading.intelligence.events.v1` | Alpha Agents | Critic Agent |
| `critic.decision_created` | Intelligence | 1 | `CriticDecisionCreatedPayload` | `trading.intelligence.events.v1` | Critic Agent | Trade Intent Synthesizer |
| `trade.intent_created` | Intelligence | 1 | `TradeIntentCreatedPayload` | `trading.intelligence.events.v1` | Intelligence Orchestrator | Risk Governor |
| `risk.decision_created` | Risk | 1 | `RiskDecisionCreatedPayload` | `trading.risk.events.v1` | Risk Governor | Execution Engine |
| `risk.limit_breached` | Risk | 1 | `RiskLimitBreachedPayload` | `trading.risk.events.v1` | Risk Governor | System Control |
| `risk.kill_switch_activated` | Risk | 1 | `RiskKillSwitchActivatedPayload` | `trading.risk.events.v1` | Risk Governor | Execution Engine |
| `order.approved` | Execution | 1 | `OrderApprovedPayload` | `trading.execution.events.v1` | Execution Engine | Exchange Router |
| `order.submission_requested` | Execution | 1 | `OrderSubmissionRequestedPayload` | `trading.execution.events.v1` | Execution Engine | Exchange Adapter |
| `order.submitted` | Execution | 1 | `OrderSubmittedPayload` | `trading.execution.events.v1` | Exchange Adapter | Order Tracker |
| `order.partially_filled` | Execution | 1 | `OrderPartiallyFilledPayload` | `trading.execution.events.v1` | Exchange Adapter | Position Manager |
| `order.filled` | Execution | 1 | `OrderFilledPayload` | `trading.execution.events.v1` | Exchange Adapter | Position Manager |
| `order.rejected` | Execution | 1 | `OrderRejectedPayload` | `trading.execution.events.v1` | Exchange Adapter | Risk Governor |
| `order.cancelled` | Execution | 1 | `OrderCancelledPayload` | `trading.execution.events.v1` | Exchange Adapter | Position Manager |
