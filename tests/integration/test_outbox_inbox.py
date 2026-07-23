import asyncio

from packages.events.envelope import DomainEventEnvelope
from packages.events.memory import InMemoryEventBus


def test_in_memory_event_bus_publish_and_consume():
    async def _run():
        bus = InMemoryEventBus()
        received_events = []

        async def _sample_handler(env: DomainEventEnvelope):
            received_events.append(env)

        await bus.subscribe("trading.event.system.started", "group_1", _sample_handler)

        env = DomainEventEnvelope(
            event_type="system.started",
            aggregate_type="system",
            aggregate_id="sys_1",
            payload={"mode": "PAPER_TRADING"}
        )
        result = await bus.publish(env)
        assert result.success is True
        assert len(received_events) == 1
        assert received_events[0].event_id == env.event_id

    asyncio.run(_run())
