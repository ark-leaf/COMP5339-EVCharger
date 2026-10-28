import asyncio
from collections.abc import Callable
import math
import threading
import time
from threading import Event
from types import TracebackType

import paho.mqtt.client as mqtt

from repository.event.y_event import YEvent
from repository.repo_config import mqtt_config

_REPO_LABEL = "Yeh's Toy MQTT Repository"
_BROKER_LABEL = "Yeh's Toy MQTT Inline Broker"
_CLIENT_LABEL = "Yeh's Toy MQTT Client"
_WILDCARD_HOSTS = ("0.0.0.0", "::", "")


class YSimpleMqttRepository:
    '''
        Ark (Qingzhou) Ye's Toy MQTT Client Repository
        An optional Toy Inline Broker also embedded
    '''
    def __init__(self,
                 host: str | None = None, port: int | None = None,
                 keepalive: int | None = None,
                 topic_prefix: str | None = None,
                 interval: float | None = None,
                 is_inline_broker: bool = True, settings: dict | None = None):
        # Initialize MQTT configurations: explicit args > settings > shared config
        self.settings = {**mqtt_config(), **(settings or {})}
        self.host = self.settings["host"] if host is None else host
        self.port = self.settings["port"] if port is None else port
        self.keepalive = self.settings["keepalive"] if keepalive is None else keepalive
        self.topic_prefix = self.settings["topic_root"] if topic_prefix is None else topic_prefix
        self.interval = self.settings["publish_interval_seconds"] if interval is None else interval
        self._is_inline_broker = is_inline_broker
        self.version = self.settings.get("version") or mqtt.CallbackAPIVersion.VERSION2

        # Validate args
        self._validate_args()

        self._broker = None
        self._broker_loop = None
        self._broker_thread = None
        self._client_connected = Event()
        self._client_connection_errors = []
        self.msg_count_sent = 0
        self.msg_count_received = 0
        self.last_sent = None
        self._client = None
        try:
            # Inline Broker daemon (if applicable)
            if is_inline_broker:
                self._start_inline_broker_daemon()
            # Initialize MQTT client daemon and connection
            self._connect_client()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None,
                 traceback: TracebackType | None):
        self.close()

    def close(self):
        """Disconnect the client, then stop the inline broker; safe to call twice."""
        self.disconnect_client()
        self._stop_inline_broker_daemon()

    def _validate_args(self):
        # Host and port
        if not self.host.strip() or type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError(f"[{_REPO_LABEL}] MQTT host and port must be valid")
        # Topic prefix
        self.topic_prefix = self.topic_prefix.strip("/")
        if not self.topic_prefix or any(c in self.topic_prefix for c in "+#\0"):
            raise ValueError(f"[{_REPO_LABEL}] Topic prefix must be nonempty and contain no wildcards")
        # Task 2: at least 0.1 seconds between published messages
        if not math.isfinite(self.interval) or self.interval < 0.1:
            raise ValueError(f"[{_REPO_LABEL}] Publication interval must be at least 0.1 seconds")

    # MQTT Inline Broker Daemon methods

    def _start_inline_broker_daemon(self):
        # Imported here so offline generation does not need amqtt installed.
        from amqtt.broker import Broker
        from amqtt.errors import BrokerError

        broker_config = {
            "listeners": {
                "default": {
                    "type": "tcp",
                    "bind": f"{self.host}:{self.port}"
                }
            },
            # amqtt >= 0.11 takes {plugin class: options}; no $SYS plugin, so no extra traffic.
            "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
        }

        async def boot() -> Broker:
            # Broker() binds to the running loop, so it must be created inside it.
            broker = Broker(broker_config)
            await broker.start()
            return broker

        # The broker runs on its own event loop thread; paho stays synchronous here.
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name=_BROKER_LABEL, daemon=True)
        thread.start()
        print(f'''
                   [{_BROKER_LABEL}] Booting inline MQTT broker...
                       - Host: {self.host}
                       - Port: {self.port}
               ''')
        try:
            self._broker = asyncio.run_coroutine_threadsafe(boot(), loop).result(timeout=10)
        except BaseException as exc:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)
            loop.close()
            if isinstance(exc, BrokerError):
                raise RuntimeError(f"[{_BROKER_LABEL}] Cannot start on {self.host}:{self.port}; "
                                   f"is another MQTT broker (e.g. Mosquitto) already running there? "
                                   f"({exc})") from exc
            raise
        self._broker_loop, self._broker_thread = loop, thread
        print(f"[{_BROKER_LABEL}] Have fun :-)")

    def _stop_inline_broker_daemon(self):
        if self._broker in [None, False]:
            return
        loop = self._broker_loop
        try:
            asyncio.run_coroutine_threadsafe(self._broker.shutdown(), loop).result(timeout=10)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            self._broker_thread.join(timeout=10)
            loop.close()
            self._broker = self._broker_loop = self._broker_thread = None
            print(f"[{_BROKER_LABEL}] Inline MQTT broker stopped")

    # MQTT client configuration methods

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self._client_connection_errors.append(str(reason_code))
        self._client_connected.set()

    def _connect_client(self):
        self._client = mqtt.Client(self.version, reconnect_on_failure=True)
        self._client.on_connect = self._on_connect

        # Optional settings (credentials must be set before connecting)
        self._client.max_inflight_messages_set(self.settings.get("max_inflight_messages") or 1)
        if self.settings.get("username"):
            self._client.username_pw_set(self.settings["username"], self.settings.get("password"))

        # A broker bound to every interface is reached locally through loopback.
        host = "127.0.0.1" if self.host in _WILDCARD_HOSTS else self.host
        self._client.connect(host, self.port, keepalive=self.keepalive)
        self._client.loop_start()
        if not self._client_connected.wait(10):
            raise TimeoutError(f"[{_CLIENT_LABEL}] MQTT broker did not acknowledge the client connection")
        if self._client_connection_errors:
            raise ConnectionError(f"[{_CLIENT_LABEL}] MQTT connection rejected: {self._client_connection_errors[0]}")

    def disconnect_client(self):
        if self._client is None:
            return
        self._client.disconnect()
        self._client.loop_stop()
        self._client = None
        print(f"[{_CLIENT_LABEL}] MQTT client disconnected")
        print(f"[{_CLIENT_LABEL}] Message sent: {self.msg_count_sent}, received: {self.msg_count_received}")

    # Event methods
    def subscribe(self, on_message: Callable[[str, bytes], None], topic_filter: str | None = None):
        """Subscribe (default "{topic_prefix}/#") and block until the broker's SUBACK.

        on_message(topic, payload) runs on paho's network thread, so hand slow work to another thread.
        """
        topic_filter = f"{self.topic_prefix}/#" if topic_filter is None else topic_filter
        subscribed, failures = Event(), []

        def _on_subscribe(client, userdata, mid, reason_codes, properties):
            failures.extend(str(code) for code in reason_codes if code.is_failure)
            subscribed.set()

        def _on_message(client, userdata, message):
            self.msg_count_received += 1
            on_message(message.topic, message.payload)

        self._client.on_subscribe = _on_subscribe
        self._client.on_message = _on_message
        result, _ = self._client.subscribe(topic_filter, qos=self.settings.get("qos") or 0)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"[{_CLIENT_LABEL}] MQTT subscribe failed: {mqtt.error_string(result)}")
        if not subscribed.wait(10):
            raise TimeoutError(f"[{_CLIENT_LABEL}] MQTT broker did not acknowledge the subscription")
        if failures:
            raise ConnectionError(f"[{_CLIENT_LABEL}] MQTT subscription rejected: {failures[0]}")
        print(f"[{_CLIENT_LABEL}] Subscribed to {topic_filter}")

    def send_event(self, event: YEvent):
        """Publish one event and wait for the broker's QoS 1 acknowledgement."""
        if self.last_sent is not None:
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_sent)))
        topic = f"{self.topic_prefix}/{event.type}/{event.object_id}"
        qos = self.settings.get("qos") or 0
        is_retain = self.settings.get("retain") or False
        message = self._client.publish(topic, event.to_json(), qos=qos, retain=is_retain)
        if message.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"[{_CLIENT_LABEL}] MQTT publish failed: {mqtt.error_string(message.rc)}")
        message.wait_for_publish(timeout=10)
        if not message.is_published():
            raise TimeoutError(f"[{_CLIENT_LABEL}] MQTT event was not acknowledged: {event.id}")
        self.last_sent = time.monotonic()  # Pace from broker ACK, not asynchronous enqueue.
        self.msg_count_sent += 1
