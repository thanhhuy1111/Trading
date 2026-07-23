from packages.events.redis_streams import RedisStreamsEventBus


def test_redis_streams_key_prefixing():
    bus = RedisStreamsEventBus(env="development")
    key = bus._get_stream_key("trading.system.events.v1")
    assert key == "trading:development:trading.system.events.v1"


def test_redis_streams_key_prefixing_production():
    bus = RedisStreamsEventBus(env="production")
    key = bus._get_stream_key("trading.risk.events.v1")
    assert key == "trading:production:trading.risk.events.v1"
