import inspect
import queue
import threading
from contextlib import contextmanager
from typing import Callable, Generic, TypeVar, get_args

from repository.event.y_event import YEvent
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository

E = TypeVar("E", bound=YEvent)
SUB_NAME="Yeh's MQTT Subscriber"


class YMqttEventSubscriber(threading.Thread, Generic[E]):
    '''
    Subscribe to event topic and pass each received event to handle_event.
    '''

    def __init__(self, name: str, handle_event: Callable[[E], None],
                 host: str, port: int, event_type: type[E] | None = None):
        super().__init__(name=name, daemon=True)
        self.handle_event = handle_event
        self.host, self.port = host, port
        self.event_type = event_type
        self.ready, self.stopping = threading.Event(), threading.Event()
        self.received = 0
        self.error = None
        self._inbox = queue.Queue()

    def start(self):
        print(f"[{SUB_NAME}] {self.name} started")
        self.event_type = self._resolve_event_type()
        super().start()

    def _resolve_event_type(self) -> type[E]:
        event_type = self.event_type
        if event_type is None:
            event_type = next(iter(get_args(getattr(self, "__orig_class__", None))), None)
        if (not isinstance(event_type, type) or not issubclass(event_type, YEvent)
                or inspect.isabstract(event_type)):
            raise TypeError(f"[{SUB_NAME}] {self.name}: the event type must be a concrete YEvent subclass, e.g. "
                            f"YMqttEventSubscriber[EVChargerStateEvent](...); got {event_type!r}")
        return event_type

    def run(self):
        try:
            event_type = self._resolve_event_type()
            with YSimpleMqttRepository(host=self.host, port=self.port, is_inline_broker=False) as repo:
                # paho calls back on its network thread; this thread decodes and handles events.
                repo.subscribe(lambda topic, payload: self._inbox.put(payload))
                self.ready.set()
                while not (self.stopping.is_set() and self._inbox.empty()):
                    try:
                        payload = self._inbox.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    self.handle_event(event_type.from_json(payload))
                    self.received += 1
        except BaseException as exc:
            self.error = exc
            raise
        finally:
            self.ready.set()  # Never leave main() waiting on a failed subscriber.


@contextmanager
def subscribed(*subscribers: YMqttEventSubscriber, timeout: float = 15.0):
    """Start the subscribers together, wait until each has subscribed, and stop them all on exit.

    They connect in parallel, so the wait is as long as the slowest one. On stopping, each
    still handles the events already queued. After a clean exit, a subscriber that failed
    while running raises here.
    """
    started = []
    try:
        for subscriber in subscribers:
            subscriber.start()
            started.append(subscriber)
        for subscriber in subscribers:
            if not subscriber.ready.wait(timeout) or subscriber.error:
                raise RuntimeError(f"{subscriber.name} did not subscribe: {subscriber.error}")
        yield subscribers
    finally:
        for subscriber in started:
            subscriber.stopping.set()
        for subscriber in started:
            subscriber.join(timeout=10)
    failed = next((subscriber for subscriber in subscribers if subscriber.error), None)
    if failed is not None:
        raise RuntimeError(f"{failed.name} failed: {failed.error!r}") from failed.error
