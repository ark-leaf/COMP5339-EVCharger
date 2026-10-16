# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that this team-authored configuration was reviewed with OpenAI Codex
# during pipeline integration, and its database filename was aligned for Ass2.

from __future__ import annotations

from config import DATA_ROOT, PROJECT_ROOT

# DuckDB Configs
DB_ROOT =  PROJECT_ROOT / "db"
DB_SCHEMA = DB_ROOT / "schema" / "nsw_evc_schema.sql"
DB_DATA = DATA_ROOT / "db" / "nsw_evc.db"
