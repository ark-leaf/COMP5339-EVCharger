# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the station-reading connection adapter.
from pathlib import Path

import duckdb

from repository.repo_config import duckdb_config
from repository.utils import duckdb_utils


class DuckDBRepository:
    '''
    A toy DuckDB Repository to access the database
    '''
    def __init__(self, db_path=None, *, read_only=None):
        config = duckdb_config()
        self.db_path = Path(db_path if db_path is not None else config["database"]).expanduser()
        # Station reads stay read-only even though shared writer settings allow writes.
        self.read_only = True if read_only is None else read_only
        self._connection = None

    def connect(self):
        if self._connection is None:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"DuckDB database not found: {self.db_path}")
            self._connection = duckdb.connect(str(self.db_path), read_only=self.read_only)
        return self

    def fetch_all(self, sql, params=None) -> list[dict]:
        if self._connection is None:
            raise RuntimeError("Database is not connected; use connect() or a with block")
        result = self._connection.execute(sql, params if params is not None else [])
        columns = [column[0] for column in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class SharedDuckDBRepository:
    '''
    Read through the process's shared connection (repository.utils.duckdb_utils).

    DuckDB will not open a file twice with different settings in one process, so a process
    that also stores events (main_ass_2) reads with the writer's connection.
    '''
    def __init__(self):
        # The shared connection would create a missing file; refuse instead, as connect() does.
        if not duckdb_utils.database_path().is_file():
            raise FileNotFoundError(f"DuckDB database not found: {duckdb_utils.database_path()}")

    def fetch_all(self, sql, params=None) -> list[dict]:
        with duckdb_utils.cursor() as cursor:
            result = cursor.execute(sql, params if params is not None else [])
            columns = [column[0] for column in result.description]
            return [dict(zip(columns, row)) for row in result.fetchall()]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass  # The shared connection stays open for the rest of the process.
