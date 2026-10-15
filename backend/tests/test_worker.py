import dramatiq
from dramatiq.brokers.stub import StubBroker

from app.workers.broker import broker
from app.workers.tasks import ping


def test_ping_logic() -> None:
    assert ping.fn("hi") == "pong: hi"


def test_ping_is_processed_by_worker() -> None:
    assert isinstance(broker, StubBroker)
    broker.flush_all()
    ping.send("hello")
    worker = dramatiq.Worker(broker, worker_timeout=50)
    worker.start()
    try:
        broker.join(ping.queue_name, fail_fast=True)
        worker.join()
    finally:
        worker.stop()
    assert broker.queues[ping.queue_name].qsize() == 0
