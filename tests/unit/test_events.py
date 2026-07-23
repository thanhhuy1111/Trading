import pytest

from packages.events.catalog import SystemStartedPayload
from packages.events.envelope import DomainEventEnvelope, EventMetadata
from packages.events.registry import EventRegistry
from packages.events.topics import Topics


def test_domain_event_envelope_instantiation():
    env = DomainEventEnvelope(
        event_type="system.started",
        aggregate_type="system",
        aggregate_id="sys_1",
        payload={"environment": "development", "mode": "PAPER_TRADING"}
    )
    assert env.event_type == "system.started"
    assert env.schema_version == 1
    assert env.payload["environment"] == "development"
    assert isinstance(env.metadata, EventMetadata)


def test_event_registry_deserialization():
    payload_dict = {"environment": "production", "mode": "PAPER_TRADING"}
    model = EventRegistry.deserialize_payload("system.started", 1, payload_dict)
    assert isinstance(model, SystemStartedPayload)
    assert model.environment == "production"


def test_event_registry_unknown_type_raises_error():
    with pytest.raises(ValueError, match="Unsupported event schema"):
        EventRegistry.deserialize_payload("unknown.event.type", 1, {})


def test_topics_registry_constants():
    assert Topics.SYSTEM_EVENTS == "trading.system.events.v1"
    assert Topics.CONFIG_EVENTS == "trading.config.events.v1"
    assert len(Topics.ALL_TOPICS) >= 7
