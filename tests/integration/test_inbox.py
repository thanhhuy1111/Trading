from uuid import uuid4


def test_inbox_duplicate_prevention_logic():
    """Verifies that sending the exact same event_id twice results in 1 business execution."""
    processed_events = []
    inbox_records = set()

    def process_event_idempotently(event_id: str, consumer_name: str):
        key = (event_id, consumer_name)
        if key in inbox_records:
            return "SKIPPED_DUPLICATE"

        inbox_records.add(key)
        processed_events.append(event_id)
        return "PROCESSED"

    event_id = str(uuid4())
    res1 = process_event_idempotently(event_id, "risk_governor")
    res2 = process_event_idempotently(event_id, "risk_governor")

    assert res1 == "PROCESSED"
    assert res2 == "SKIPPED_DUPLICATE"
    assert len(processed_events) == 1
    assert len(inbox_records) == 1


def test_inbox_handler_failure_then_retry_success():
    """Verifies message is not marked PROCESSED until handler succeeds."""
    inbox_status = {}
    attempts = 0

    def process_with_retry(event_id: str):
        nonlocal attempts
        attempts += 1
        inbox_status[event_id] = "PROCESSING"

        if attempts == 1:
            inbox_status[event_id] = "FAILED"
            raise RuntimeError("Transient handler error")

        inbox_status[event_id] = "PROCESSED"

    event_id = str(uuid4())

    # Attempt 1 -> fails
    try:
        process_with_retry(event_id)
    except RuntimeError:
        pass
    assert inbox_status[event_id] == "FAILED"

    # Attempt 2 -> succeeds
    process_with_retry(event_id)
    assert inbox_status[event_id] == "PROCESSED"
    assert attempts == 2
