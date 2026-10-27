"""MQTT helpers shared by the data generator (publisher) and the dashboard
(subscriber).

Payloads are JSON objects. Topics follow
``{topic_root}/{event_type}/{charger_id}``, so a subscriber can take every
event with ``build_filter()`` or narrow it to one event type or charger.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import date, datetime
from decimal import Decimal

import paho.mqtt.client as mqtt

from repository.repo_config import mqtt_config

logger = logging.getLogger(__name__)


class EVCMqttClient(mqtt.Client):
    """paho client that remembers its JSON subscriptions.

    The broker forgets subscriptions when a clean session reconnects, so they
    are re-sent from ``json_subscriptions`` on every CONNACK. Callers should
    not replace ``on_connect``.
    """

    def __init__(self, client_id):
        super().__init__(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self.json_subscriptions = {}
        self.connect_reason = None
        self.connected_event = threading.Event()
        self.on_connect = _on_connect
        self.on_disconnect = _on_disconnect


def _on_connect(client, userdata, flags, reason_code, properties):
    client.connect_reason = reason_code
    client.connected_event.set()
    if reason_code.is_failure:
        logger.error("MQTT connection refused: %s", reason_code)
        return
    logger.info("MQTT connected to %s:%s", client.host, client.port)
    for topic_filter, qos in list(client.json_subscriptions.items()):
        client.subscribe(topic_filter, qos)


def _on_disconnect(client, userdata, flags, reason_code, properties):
    client.connected_event.clear()
    if reason_code.is_failure:
        logger.warning("MQTT disconnected unexpectedly: %s", reason_code)


def create_client(client_id=None):
    """Create an MQTT client configured from ``mqtt_config()``.

    Args:
        client_id: Broker client id; a random one with the configured prefix
            is generated when omitted.

    Returns:
        EVCMqttClient: A client that is not yet connected.
    """
    settings = mqtt_config()
    if client_id is None:
        client_id = f"{settings['client_id_prefix']}-{uuid.uuid4().hex[:8]}"
    client = EVCMqttClient(client_id)
    if settings["username"]:
        client.username_pw_set(settings["username"], settings["password"])
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # One message in flight at a time keeps QoS 1 delivery in publish order.
    client.max_inflight_messages_set(1)
    return client


def connect(client, start_loop=True, timeout=10.0):
    """Connect to the configured broker and wait for it to accept.

    Args:
        client: Client from ``create_client()``.
        start_loop: Start paho's background network thread. Pass False when
            the caller will run ``client.loop_forever()`` itself.
        timeout: Seconds to wait for the broker's CONNACK.

    Raises:
        ConnectionError: If the broker is unreachable or refuses the client.
    """
    settings = mqtt_config()
    host, port = settings["host"], settings["port"]
    try:
        client.connect(host, port, keepalive=settings["keepalive"])
    except OSError as exc:
        raise ConnectionError(
            f"Cannot reach MQTT broker at {host}:{port}; is Mosquitto running?"
        ) from exc
    if not start_loop:
        return
    client.loop_start()
    if not client.connected_event.wait(timeout):
        client.loop_stop()
        raise ConnectionError(f"No CONNACK from MQTT broker at {host}:{port}")
    if client.connect_reason.is_failure:
        client.loop_stop()
        raise ConnectionError(
            f"MQTT broker at {host}:{port} refused connection: "
            f"{client.connect_reason}"
        )


def disconnect(client):
    """Disconnect cleanly and stop the background network thread."""
    client.disconnect()
    client.loop_stop()


def _topic_segment(value):
    segment = str(value)
    if not segment or any(char in segment for char in "/+#"):
        raise ValueError(f"Invalid MQTT topic segment: {segment!r}")
    return segment


def build_topic(event_type, charger_id=None):
    """Return the topic for one event type, optionally for one charger.

    Examples:
        build_topic("price_update", 17) -> "evc/price_update/17"
    """
    segments = [mqtt_config()["topic_root"], _topic_segment(event_type)]
    if charger_id is not None:
        segments.append(_topic_segment(charger_id))
    return "/".join(segments)


def build_filter(event_type=None):
    """Return a subscription filter for every event, or for one event type."""
    root = mqtt_config()["topic_root"]
    if event_type is None:
        return f"{root}/#"
    return f"{root}/{_topic_segment(event_type)}/#"


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    # numpy / pandas scalars, e.g. values taken from a DataFrame row
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def encode_payload(payload):
    """Serialise a dict to UTF-8 JSON bytes.

    Datetimes become ISO-8601 strings. NaN and infinity are rejected so
    missing values must be cleaned (e.g. to None) before publishing.
    """
    return json.dumps(
        payload, default=_json_default, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def decode_payload(message):
    """Parse an MQTT message's JSON object payload.

    Returns:
        dict | None: The payload, or None (logged) if it is not a JSON object.
    """
    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Dropping malformed message on %s: %s", message.topic, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Dropping non-object message on %s", message.topic)
        return None
    return payload


def publish_json(client, topic, payload, qos=None, retain=False, wait=True,
                 timeout=10.0):
    """Publish a dict as JSON.

    Args:
        client: A connected client.
        topic: Topic from ``build_topic()``.
        payload: JSON-serialisable dict.
        qos: Defaults to the configured QoS.
        retain: Ask the broker to keep this as the topic's last message.
        wait: Block until the broker acknowledges (QoS 1/2) or the message
            is written to the socket (QoS 0).
        timeout: Seconds to wait when ``wait`` is True.

    Returns:
        mqtt.MQTTMessageInfo: paho's handle for the message.

    Raises:
        RuntimeError: If the message cannot be published, e.g. the client is
            disconnected. paho keeps QoS 1 messages queued and may still send
            them after reconnecting, so subscribers should de-duplicate.
        TimeoutError: If ``wait`` is True and it is not acknowledged in time.
    """
    if qos is None:
        qos = mqtt_config()["qos"]
    info = client.publish(topic, encode_payload(payload), qos=qos, retain=retain)
    if wait:
        info.wait_for_publish(timeout)
        if not info.is_published():
            raise TimeoutError(f"Publish to {topic} not acknowledged in {timeout}s")
    elif info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(
            f"Publish to {topic} failed: {mqtt.error_string(info.rc)}"
        )
    return info


def subscribe_json(client, subscription, handler, qos=None):
    """Call ``handler(topic, payload_dict)`` for each JSON message received.

    The subscription is kept across reconnects. Messages that are not JSON
    objects are logged and skipped, and an exception raised by ``handler`` is
    logged rather than stopping paho's network thread. Handlers run on that
    thread one message at a time, in arrival order.

    Args:
        client: Client from ``create_client()``; may be connected or not.
        subscription: MQTT topic filter, e.g. from ``build_filter()``.
        handler: Callable taking the message topic and decoded payload.
        qos: Defaults to the configured QoS.
    """
    if qos is None:
        qos = mqtt_config()["qos"]

    def on_message(_client, _userdata, message):
        payload = decode_payload(message)
        if payload is None:
            return
        try:
            handler(message.topic, payload)
        except Exception:
            logger.exception("Handler failed for message on %s", message.topic)

    client.message_callback_add(subscription, on_message)
    client.json_subscriptions[subscription] = qos
    if client.is_connected():
        result, _ = client.subscribe(subscription, qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"Subscribe to {subscription} failed: {mqtt.error_string(result)}"
            )
