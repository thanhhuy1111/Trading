import asyncio
import json
from typing import List, Sequence

from packages.common.config import settings
from packages.common.logger import logger
from packages.events.bus import EventHandler, PublishResult
from packages.events.envelope import DomainEventEnvelope


class RedisStreamsEventBus:
    """Redis Streams Event Bus adapter for minimal profile."""

    def __init__(self, redis_url: str = settings.REDIS_URL, env: str = settings.ENVIRONMENT):
        self.redis_url = redis_url
        self.env = env
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def _get_stream_key(self, topic: str) -> str:
        return f"trading:{self.env}:{topic}"

    async def publish(self, event: DomainEventEnvelope) -> PublishResult:
        topic = f"trading.{event.event_type}"
        stream_key = self._get_stream_key(topic)
        payload_str = event.model_dump_json()

        try:
            import redis.asyncio as redis
            r = redis.from_url(self.redis_url, socket_timeout=2.0)
            async with r:
                msg_id = await r.xadd(stream_key, {"envelope": payload_str}, maxlen=10000)
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                return PublishResult(
                    success=True,
                    event_id=str(event.event_id),
                    topic=topic,
                    offset_or_message_id=msg_id_str
                )
        except Exception as e:
            logger.error("RedisStreams publish error", extra={"error": str(e), "event_id": str(event.event_id)})
            return PublishResult(
                success=False,
                event_id=str(event.event_id),
                topic=topic,
                error_code="REDIS_STREAMS_ERROR",
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
        stream_key = self._get_stream_key(topic)

        async def _consumer_loop():
            import redis.asyncio as redis
            r = redis.from_url(self.redis_url, socket_timeout=5.0)
            consumer_name = f"consumer_{settings.ENVIRONMENT}_{group_id}"
            
            # Create group if not exists
            try:
                await r.xgroup_create(stream_key, group_id, id="0", mkstream=True)
            except Exception:
                pass  # Already exists

            while self._running:
                try:
                    entries = await r.xreadgroup(
                        group_id=group_id,
                        consumer_name=consumer_name,
                        streams={stream_key: ">"},
                        count=10,
                        block=2000
                    )
                    if entries:
                        for _s_name, messages in entries:
                            for msg_id, data in messages:
                                raw_env = data.get(b"envelope") or data.get("envelope")
                                if raw_env:
                                    env_dict = json.loads(raw_env)
                                    envelope = DomainEventEnvelope.model_validate(env_dict)
                                    await handler(envelope)
                                await r.xack(stream_key, group_id, msg_id)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("Redis consumer loop exception", extra={"error": str(e)})
                    await asyncio.sleep(1)

        task = asyncio.create_task(_consumer_loop())
        self._tasks.append(task)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
