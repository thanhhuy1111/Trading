# Exchange Simulator Specification

## 1. Overview
`SimulatorExchangeAdapter` provides a deterministic in-memory order fill simulation for Spot MVP trading (`BUY` side ONLY).

## 2. Fill Pricing & Fees
- **Slippage**: Default 5.0 bps ($0.05\%$).
- **Fill Price Formula**: $P_{fill} = \min(P_{limit} \times (1 + Slippage_{bps}/10000), P_{limit}, P_{max\_entry})$
- **Taker Fee**: 10.0 bps ($0.10\%$) in USDT.
- **Idempotency**: Lookup by `client_order_id` ensures duplicate submissions return existing order responses without creating new fills.
