import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import (
    AgeLimit,
    AsyncIO,
    Callbacks,
    Pipelines,
    Retries,
    ShutdownNotifications,
    TimeLimit,
)

from app.core.config import get_settings
from app.workers.observability import observability_middleware


def create_broker() -> dramatiq.Broker:
    settings = get_settings()
    middleware = [
        AgeLimit(),
        TimeLimit(),
        ShutdownNotifications(),
        Callbacks(),
        Pipelines(),
        Retries(),
        AsyncIO(),
        *observability_middleware(settings),
    ]
    if settings.app_env == "test":
        stub = StubBroker(middleware=middleware)
        stub.emit_after("process_boot")
        return stub
    return RedisBroker(url=settings.redis_url, middleware=middleware)  # type: ignore[no-untyped-call]


broker = create_broker()
dramatiq.set_broker(broker)
