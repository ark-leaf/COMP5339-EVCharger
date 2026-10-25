# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the DuckDB configuration.
from pipeline.data_load.nsw_evc_load_config import DB_DATA


def duckdb_config():
    """Shared Ass2 defaults; pass a different snapshot path to the repository."""
    return {
        "database": DB_DATA,
        "read_only": True,
    }


def mqtt_config():
    # Reserved for shared settings; A's publisher currently uses CLI arguments.
    pass
