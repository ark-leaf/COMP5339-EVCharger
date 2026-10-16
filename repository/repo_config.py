from __future__ import annotations

from config import (
    MQTT_CLIENT_ID_PREFIX,
    MQTT_HOST,
    MQTT_KEEPALIVE_SECONDS,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_PUBLISH_INTERVAL_SECONDS,
    MQTT_QOS,
    MQTT_TOPIC_ROOT,
    MQTT_USERNAME,
)
from pipeline.data_load.nsw_evc_load_config import DB_DATA


def duckdb_config():
    """Return the DuckDB settings shared by the repository layer.

    Assignment 2 events are stored in the same database file as the
    Assignment 1 charger tables so they can be joined on charger_id.

    Returns:
        dict: database path, read-only flag and extensions to load.
    """
    return {
        "database": DB_DATA,
        "read_only": False,
        "extensions": ("spatial",),
    }


def mqtt_config():
    """Return the MQTT broker, topic and publishing settings.

    Returns:
        dict: broker address, credentials, topic root, QoS and publish interval.
    """
    return {
        "host": MQTT_HOST,
        "port": MQTT_PORT,
        "keepalive": MQTT_KEEPALIVE_SECONDS,
        "username": MQTT_USERNAME,
        "password": MQTT_PASSWORD,
        "client_id_prefix": MQTT_CLIENT_ID_PREFIX,
        "topic_root": MQTT_TOPIC_ROOT,
        "qos": MQTT_QOS,
        "publish_interval_seconds": MQTT_PUBLISH_INTERVAL_SECONDS,
    }
