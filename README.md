# COMP5339 Assignment 1

## Task 1 scaffold: Data Acquisition

This workspace contains a scaffold for the first assignment task. The student must implement the download, extraction, validation and manifest logic in `scripts/acquire_data.py`.

### Sources fixed by the brief

- Transport for NSW EV locations: December 2025 resource, saved as `data/raw/ev_20251216.csv`.
- ABS ASGS Edition 4 SA4 boundary: 2026 GDA2020 shapefile ZIP, saved as `data/raw/SA4_2026_AUST_SHP_GDA2020.zip` and extracted below `data/raw/sa4_2026_gda2020/`.

### Suggested project structure

```text
assignment1/
  data/
    metadata/
    raw/
  scripts/
    acquire_data.py
  requirements.txt
  README.md
```

### Your implementation checklist

- Use the URLs already defined in `scripts/acquire_data.py`.
- Make the script runnable from any current working directory.
- Create output directories automatically.
- Handle HTTP failures and incomplete downloads.
- Avoid overwriting a valid local copy unless explicitly requested.
- Extract the ABS archive safely.
- Confirm that the EV CSV exists and that the extracted SA4 dataset contains `.shp`, `.dbf`, `.shx` and `.prj` files.
- Write `data/metadata/acquisition_manifest.json` with retrieval time, source URLs, local paths, file sizes and validation results.
- Record the final row/file counts after you run the script.

### Run

Create and activate a virtual environment, install the packages you selected in `requirements.txt`, then run:

```text
python scripts/acquire_data.py
```

Do not claim Task 1 is complete until the raw files and manifest have been checked locally.

### Source notes

The EV resource is the December 2025 file `ev_20251216.csv`. The ABS resource is the latest SA4 2026 GDA2020 shapefile listed on the ASGS Edition 4 digital-boundary page. Cite both URLs and their access date in the report.
