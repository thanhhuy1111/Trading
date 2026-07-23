# Durable Event Journal Specification

## 1. Overview
The Durable Event Journal (`packages/paper/journal.py`) provides append-only persistence of all public market data events, connection state transitions, trade intents, paper orders, fills, and ledger entries during Paper Trading sessions.

---

## 2. Table Schema (`paper_event_journal`)
| Column | Type | Description |
|---|---|---|
| `journal_id` | UUID (PK) | Unique entry identifier |
| `session_id` | UUID (FK) | Paper session ID |
| `event_type` | VARCHAR(100) | `candle_close`, `order_submitted`, `fill_executed`, `incident` |
| `event_id` | UUID | Original domain event UUID |
| `source` | VARCHAR(100) | Event origin (`public_stream`, `paper_pipeline`, `adapter`) |
| `exchange_event_time` | TIMESTAMPTZ | Time of event on exchange |
| `received_at` | TIMESTAMPTZ | System receipt timestamp |
| `processed_at` | TIMESTAMPTZ | Pipeline completion timestamp |
| `sequence_number` | BIGINT | Monotonic sequence number for session |
| `payload_checksum` | VARCHAR(64) | SHA256 fingerprint of event payload |
| `schema_version` | INTEGER | Schema version (default: 1) |

---

## 3. Cryptographic Tamper Evident Integrity
Every entry includes a `payload_checksum` calculated via:
```python
SHA256(f"{session_id}:{sequence_number}:{event_type}:{payload_str}".encode("utf-8"))
```
Replaying journal entries validates SHA256 integrity to detect data corruption or unauthorized tampering.
