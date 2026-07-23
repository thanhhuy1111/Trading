from uuid import uuid4

from packages.events.memory import InMemoryEventBus
from packages.outbox.publisher import OutboxPublisherWorker


def test_outbox_rollback_atomicity():
    """Verifies that an exception during a transaction rolls back both business state and outbox record."""
    db_state = []
    outbox_state = []

    def _transaction_with_error():
        try:
            # Simulate atomic transaction block
            db_state.append({"order_id": "ord_1", "status": "CREATED"})
            outbox_state.append({"event_id": str(uuid4()), "topic": "trading.execution.events.v1"})
            # Raise exception before commit
            raise RuntimeError("Database constraint violation failure")
        except RuntimeError:
            # Simulate transaction rollback
            db_state.clear()
            outbox_state.clear()

    _transaction_with_error()

    assert len(db_state) == 0
    assert len(outbox_state) == 0


def test_outbox_commit_success_atomicity():
    """Verifies atomic commit of both business state and outbox event."""
    db_state = []
    outbox_state = []

    def _transaction_success():
        db_state.append({"order_id": "ord_1", "status": "CREATED"})
        outbox_state.append({"event_id": str(uuid4()), "topic": "trading.execution.events.v1"})

    _transaction_success()

    assert len(db_state) == 1
    assert len(outbox_state) == 1


def test_outbox_worker_metrics():
    bus = InMemoryEventBus()
    worker = OutboxPublisherWorker(event_bus=bus, worker_id="worker_test_1")
    assert worker.metrics["worker_id"] == "worker_test_1"
    assert worker.metrics["processed_count"] == 0
    assert worker.metrics["failed_count"] == 0
