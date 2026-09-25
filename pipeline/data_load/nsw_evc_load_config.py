# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that this team-authored configuration was reviewed with OpenAI Codex
# during pipeline integration. The team's original path assignments were retained.

from __future__ import annotations

from config import DATA_ROOT, PROJECT_ROOT

# DuckDB Configs
DB_ROOT =  PROJECT_ROOT / "db"
DB_SCHEMA = DB_ROOT / "schema" / "nsw_evc_schema.sql"
DB_DATA = DATA_ROOT / "db" / ".duckdb"
