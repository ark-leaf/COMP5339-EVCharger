# USYD CODE CITATION ACKNOWLEDGEMENT
# Yeh's shared configuration interface aligned with OpenAI Codex assistance.
from config import (
    MQTT_CLIENT_ID_PREFIX, MQTT_HOST, MQTT_KEEPALIVE_SECONDS, MQTT_PASSWORD,
    MQTT_PORT, MQTT_PUBLISH_INTERVAL_SECONDS, MQTT_QOS, MQTT_TOPIC_ROOT, MQTT_USERNAME,
)
from pipeline.data_load.nsw_evc_load_config import DB_DATA


def duckdb_config():
    """Shared writer settings for Yeh's helpers; A opens its snapshot read-only."""
    return {
        "database": DB_DATA,
        "read_only": False,
        "extensions": ("spatial",),
    }


def mqtt_config():
    """Shared MQTT settings for A's publisher and Yeh's subscriber helpers."""
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
