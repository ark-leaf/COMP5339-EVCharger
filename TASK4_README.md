# Task 4 — Data Transformation and Storage

## Completion status

Task 4 is complete. It provides a six-table relational schema in a file-backed
DuckDB database, DuckDB Spatial geometry columns, reproducible DDL and loading,
and final relational, Task 3 integration, and spatial consistency validation.

## Inputs

Task 4 uses two runtime data inputs:

- `aug_data/nsw_ev_charging.csv` — the single primary charger dataset, containing all 1,958 cleaned rows together with accepted Task 3 enrichment fields.
- `data/raw/sa4_2026_gda2020/SA4_2026_AUST_GDA2020.shp` — ABS SA4 attributes and polygon geometry used to populate `sa4_region`.

`clean_src_data/nsw_ev_charging.csv` and the Task 3 audit outputs are upstream/reference artifacts only; they are not read directly by the Task 4 loader.

## Database schema

The database contains six tables:

| Table | Purpose |
|---|---|
| `operator` | Cleaned base operator names and deterministic local IDs |
| `sa4_region` | ABS SA4 metadata and polygon geometry |
| `charger_location` | Charger identity, location, point geometry, operator, and SA4 assignment |
| `charger_characteristic` | One-to-one charger type, plug count, and rating attributes |
| `charger_connector` | Atomic normalized connector types for accepted Task 3 enrichments |
| `augmentation_record` | Accepted external attributes, match evidence, and provenance |

See [`database_schema_design.md`](database_schema_design.md) for the detailed ER
design, source mapping, cardinalities, and normalization rationale.

## Spatial design

Source charger coordinates use EPSG:4326. The loader creates points with
GeoPandas, transforms them to EPSG:7844, converts the geometries to WKT, and
stores them in DuckDB `GEOMETRY` columns. The ABS SA4 polygons also use
EPSG:7844.

Task 2 assigned SA4 regions with the GeoPandas `within` predicate. Task 4 keeps
that upstream assignment and validates the equivalent polygon/point relation
with DuckDB Spatial `ST_Contains`. `ST_Intersects` is used only for diagnostics.

## Build process

[`scripts/task4_load_duckdb.py`](scripts/task4_load_duckdb.py) is the only entry
point. It:

1. executes `sql/task4_schema.sql` and recreates the six tables;
2. loads operator and Australia-wide SA4 parent data;
3. loads charger locations and one-to-one characteristics;
4. loads normalized connectors and accepted Task 3 augmentation records; and
5. validates table counts, PK/FK integrity, Task 3 integration, and spatial
   consistency.

The loading functions are in `scripts/task4_loaders.py`; validation functions
are in `scripts/task4_validation.py`.

## Reproduce

The project uses Python 3.11. From the repository root, the environment can be
created with the same `uv` workflow used for the verified local build:

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Run the complete clean rebuild with:

```powershell
.\.venv\Scripts\python.exe scripts\task4_load_duckdb.py
```

The loader always executes the DDL `DROP`/`CREATE` statements before loading,
so the result does not depend on rows left in an earlier database.

## Final outputs

- `data/processed/task4.duckdb` — final database deliverable
- `sql/task4_schema.sql` — executable DDL
- `database_schema_design.md` — detailed ER and schema design
- `scripts/task4_load_duckdb.py` — pipeline entry point
- `scripts/task4_loaders.py` — loading functions
- `scripts/task4_validation.py` — staged and final validation functions

## Final validation

| Table | Rows |
|---|---:|
| `operator` | 45 |
| `sa4_region` | 108 |
| `charger_location` | 1,958 |
| `charger_characteristic` | 1,958 |
| `charger_connector` | 369 |
| `augmentation_record` | 239 |

Spatial validation found 1,957 assigned chargers, one unassigned charger,
1,957 spatially consistent assignments, and zero mismatches. Task 3 integration
validation found 239 accepted augmentation rows, 369 deduplicated normalized
connector rows, zero review-only leakage, and zero unmatched leakage. All PK,
FK, orphan, connector uniqueness, and location/characteristic one-to-one checks
passed.

## Known data conditions

- The ABS source includes 19 non-spatial statistical classification records;
  they are retained with `geometry` stored as NULL.
- One charger has no upstream SA4 assignment and has no intersecting SA4
  candidate in the final spatial diagnostic.
- `rating_kw` is the highest parsed available power represented by the existing
  Task 2 `Charger_rating.*kW` columns.
- `augmentation_match_confidence` is a deterministic rule score, not a
  calibrated probability.
