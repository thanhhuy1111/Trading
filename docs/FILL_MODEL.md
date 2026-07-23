# Fill Model Specification

## 1. Fill Invariants
- `quantity > 0`
- `price > 0`
- `quote_quantity = quantity * price`
- `fee >= 0`
- `price <= maximum_entry_price`
- Fills are immutable once generated and saved to PostgreSQL `fills` table.
