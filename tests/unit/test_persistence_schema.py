"""Design-level verification of the durable paper schema (no DB server needed).

Verifies the DDL compiles for the PostgreSQL dialect and that the idempotency-critical unique
constraints and lookup indexes exist. This does NOT verify anything runs on a real database.
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from packages.persistence import schema


def test_all_tables_compile_for_postgres() -> None:
    dialect = postgresql.dialect()
    for table in schema.ALL_TABLES:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl
        for index in table.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=dialect))


def test_idempotency_unique_constraints_present() -> None:
    def uq_names(table):
        return {c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"}

    assert "uq_paper_candle_key" in uq_names(schema.paper_processed_candles)
    assert "uq_paper_order_client_id" in uq_names(schema.paper_orders)
    assert "uq_paper_position_session_symbol" in uq_names(schema.paper_positions)
    assert "uq_paper_pnl_bucket" in uq_names(schema.paper_pnl_buckets)
    # fill_id is the primary key of paper_fills -> globally unique
    assert schema.paper_fills.primary_key.columns.keys() == ["fill_id"]


def test_candle_unique_key_columns() -> None:
    uq = next(
        c for c in schema.paper_processed_candles.constraints
        if getattr(c, "name", None) == "uq_paper_candle_key"
    )
    assert [col.name for col in uq.columns] == ["session_id", "symbol", "timeframe", "close_time"]


def test_expected_indexes_present() -> None:
    index_names = {ix.name for t in schema.ALL_TABLES for ix in t.indexes}
    for expected in [
        "ix_paper_candles_session_close",
        "ix_paper_orders_session_created",
        "ix_paper_fills_session_event",
        "ix_paper_ledger_session_event",
        "ix_paper_positions_session_symbol",
        "ix_paper_pnl_buckets_key",
    ]:
        assert expected in index_names
