import asyncio
import json
from typing import List, Sequence

from packages.common.config import settings
from packages.common.logger import logger
from packages.events.bus import EventHandler, PublishResult
from packages.events.envelope import DomainEventEnvelope


class RedpandaEventBus:
    """Redpanda / Kafka Event Bus adapter for full profile."""

    def __init__(self, brokers: str = settings.REDPANDA_BROKERS):
        self.brokers = brokers
        self._running = False
        self._tasks: List[asyncio.Task] = []

    async def publish(self, event: DomainEventEnvelope) -> PublishResult:
        topic = f"trading.{event.event_type}"
        try:
            from kafka import KafkaProducer
            producer = KafkaProducer(
                bootstrap_servers=self.brokers.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None
            )
            future = producer.send(
                topic,
                key=event.aggregate_id,
                value=event.model_dump(mode="json")
            )
            record_metadata = future.get(timeout=10.0)
            producer.close()
            return PublishResult(
                success=True,
                event_id=str(event.event_id),
                topic=topic,
                partition=record_metadata.partition,
                offset_or_message_id=str(record_metadata.offset)
            )
        except Exception as e:
            logger.warning("Redpanda publish failed", extra={"error": str(e), "brokers": self.brokers})
            return PublishResult(
                success=False,
                event_id=str(event.event_id),
                topic=topic,
                error_code="REDPANDA_ERROR",
                error_message=str(e)
            )

    async def publish_batch(
        self,
        events: Sequence[DomainEventEnvelope]
    ) -> List[PublishResult]:
        results = []
        for ev in events:
            res = await self.publish(ev)
            results.append(res)
        return results

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        handler: EventHandler
    ) -> None:
        self._running = True

        async def _consumer_loop():
            try:
                from kafka import KafkaConsumer
                consumer = KafkaConsumer(
                    topic,
                    bootstrap_servers=self.brokers.split(","),
                    group_id=group_id,
                    enable_auto_commit=False,
                    value_deserializer=lambda m: json.loads(m.decode("utf-8"))
                )
                while self._running:
                    records = consumer.poll(timeout_ms=1000)
                    for _tp, messages in records.items():
                        for msg in messages:
                            envelope = DomainEventEnvelope.model_validate(msg.value)
                            await handler(envelope)
                        consumer.commit()
            except Exception as e:
                logger.warning("Redpanda consumer exception", extra={"error": str(e)})

        task = asyncio.create_task(_consumer_loop())
        self._tasks.append(task)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
