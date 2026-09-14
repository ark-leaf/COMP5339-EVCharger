"""File utility operations for data processing.

This module provides utilities for file operations including downloading files,
extracting archives, and writing DataFrames to various formats with support
for append modes and nested JSON structures.
"""

import zipfile
from pathlib import Path
from typing import Iterator, Optional, Dict, Any

import pandas as pd
import requests


class YFileUtils:
    """Utility class for file operations.

    Provides static methods for common file operations used in data processing:
    - Creating directories
    - Downloading files from URLs
    - Extracting ZIP archives
    - Writing DataFrames to CSV/JSON with various options

    All methods are static and can be called directly on the class without instantiation.

    Examples:
        Creating a directory:
            YFileUtils.create_dir_if_not_exist('output/data')

        Downloading a file:
            YFileUtils.download_file('https://example.com/data.zip', 'local/data.zip')

        Writing DataFrame:
            YFileUtils.write_df(df, 'output.csv', mode='a')
    """
    @staticmethod
    def create_dir_if_not_exist(dir_path: str) -> None:
        """Create directory and all parent directories if they don't exist.

        Uses pathlib to handle cross-platform path operations. If the directory
        already exists, this method does nothing (idempotent operation).

        Args:
            dir_path (str): Path to the directory to create. Can be a file path
                           (parent directories will be created).

        Returns:
            None

        Note:
            - This method is idempotent and safe to call multiple times
            - Uses parents=True to create intermediate directories
            - Uses exist_ok=True to avoid errors if directory exists
            - Works cross-platform (handles both Windows and Unix paths)

        Examples:
            Create a simple directory:
                YFileUtils.create_dir_if_not_exist('output')

            Create nested directories:
                YFileUtils.create_dir_if_not_exist('data/processed/results')

            Create parent directories for a file path:
                YFileUtils.create_dir_if_not_exist('output/data/results.csv')
        """
        file_path = Path(dir_path)
        # Create parent directories including any intermediate directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def download_file(url: str, output_file_name: str) -> None:
        """Download a file from a URL and save it to local storage.

        Downloads files using HTTP with streaming to handle large files efficiently
        without loading entire file into memory. Creates parent directories if needed.

        Args:
            url (str): URL of the file to download. Must be a valid HTTP(S) URL.
                      Example: 'https://example.com/data/file.csv'

            output_file_name (str): Local file path where the downloaded file will be saved.
                                   Parent directories will be created automatically.
                                   Example: 'data/downloaded/file.csv'

        Returns:
            None

        Raises:
            requests.exceptions.HTTPError: If the HTTP response indicates an error
                                          (4xx or 5xx status codes).
            requests.exceptions.RequestException: For network-related errors
                                                 (timeout, connection failed, etc.).
            IOError: If the file cannot be written to the specified location
                    (permission denied, disk full, etc.).

        Note:
            - Uses streaming mode to handle large files efficiently
            - Chunks data in 8KB blocks to balance memory and performance
            - Overwrites existing files without warning
            - Filters out keep-alive chunks to avoid writing empty data
            - Automatically creates parent directories
            - Preserves the file's binary format (suitable for all file types)

        Examples:
            Download a CSV file:
                YFileUtils.download_file(
                    'https://opendata.com/data.csv',
                    'data/downloaded_data.csv'
                )

            Download a ZIP archive:
                YFileUtils.download_file(
                    'https://example.com/files/archive.zip',
                    'downloads/archive.zip'
                )

        Performance:
            - Chunk size: 8KB per iteration
            - Memory usage: ~8KB regardless of file size
            - Suitable for files of any size
        """
        # Create parent directories for the output file
        YFileUtils.create_dir_if_not_exist(output_file_name)

        # Stream the file from URL to local storage
        with requests.get(url, stream=True) as response:
            # Raise exception for HTTP errors (404, 500, etc.)
            response.raise_for_status()

            # Write file in chunks to local storage
            # Stream=True prevents loading entire file into memory
            with open(output_file_name, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    # Filter out keep-alive new chunks (empty chunks sent as heartbeat)
                    if chunk:
                        file.write(chunk)
    @staticmethod
    def unzip_file(zip_file_path: str, extract_dir_path: str) -> None:
        """Extract a ZIP archive to a local directory.

        Extracts all files and directories from a ZIP archive to the specified
        location. Creates the extraction directory if it doesn't exist.

        Args:
            zip_file_path (str): Path to the ZIP file to extract.
                                Must be a valid ZIP archive.
                                Example: 'downloads/archive.zip'

            extract_dir_path (str): Directory path where files will be extracted.
                                   Will be created if it doesn't exist.
                                   Directory structure inside ZIP is preserved.
                                   Example: 'data/extracted'

        Returns:
            None

        Raises:
            FileNotFoundError: If the ZIP file doesn't exist at the specified path.
            zipfile.BadZipFile: If the file is not a valid ZIP archive.
            OSError: If there are permission issues or disk space problems
                    during extraction.

        Note:
            - Preserves the directory structure from inside the ZIP file
            - Extracts all files (no selective extraction)
            - Overwrites existing files without warning
            - Automatically creates the extraction directory
            - Works with all standard ZIP formats
            - Does NOT require external tools (uses Python's built-in zipfile)

        Examples:
            Extract a downloaded archive:
                YFileUtils.unzip_file(
                    'downloads/data.zip',
                    'data/raw'
                )

            Extract geographic data:
                YFileUtils.unzip_file(
                    'downloads/SA4_2026_AUST_SHP.zip',
                    'data/geographic/boundaries'
                )

        Performance:
            - Speed depends on file size and disk I/O speed
            - Memory usage is minimal (streams extraction)
            - Suitable for large archives
        """
        # Create extraction directory and any parent directories
        YFileUtils.create_dir_if_not_exist(extract_dir_path)

        # Open ZIP file and extract all contents
        with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
            # extractall() preserves the directory structure from inside the ZIP
            zip_ref.extractall(extract_dir_path)

    @staticmethod
    def write_df(df: pd.DataFrame, file_name: str, mode: str = 'w',
                 flatten_keys: Optional[Dict[str, str]] = None) -> None:
        """Write DataFrame to CSV or JSON file with flexible formatting options.

        Writes a pandas DataFrame to either CSV or JSON format, determined by the
        file extension. Supports both write (overwrite) and append modes with
        format-specific handling.

        Args:
            df (pd.DataFrame): DataFrame containing the data to write.
                             All data types are handled automatically.

            file_name (str): Output file path with extension (.csv or .json).
                           Determines the output format.
                           Parent directories are created automatically.
                           Examples:
                           - 'output/data.csv'
                           - 'results/locations.json'

            mode (str, optional): Write mode. Defaults to 'w'.
                                 - 'w': Write mode (create new or overwrite existing)
                                 - 'a': Append mode (add data to existing file)
                                        For CSV: new rows are appended without header
                                        For JSON: new records are added to array

            flatten_keys (Dict[str, str], optional): For JSON output only.
                                                     Maps flat DataFrame column names
                                                     to nested JSON paths.
                                                     Used to convert flat CSV/DataFrame
                                                     structure to nested JSON.
                                                     Defaults to None (flat JSON).
                                                     Example: {'lat': 'location.lat',
                                                               'lon': 'location.lon',
                                                               'address': 'location.street'}

        Returns:
            None

        Raises:
            ValueError: If file extension is not .csv or .json.
            IOError: If file cannot be written (permission denied, disk full, etc.).
            TypeError: If DataFrame contains non-serializable data types in JSON mode.

        Note:
            CSV Mode:
            - Writes with columns as header row
            - NaN values are represented as empty strings
            - Index is not written (index=False)
            - Append mode automatically omits header to avoid duplication
            - Suitable for tabular data

            JSON Mode:
            - Converts DataFrame rows to JSON records (one dict per row)
            - NaN values are automatically excluded from output
            - Null values are preserved as null in JSON
            - Supports nested structure via flatten_keys parameter
            - Pretty-printed with 2-space indentation for readability
            - Append mode reads existing data and extends the array
            - Suitable for hierarchical/document-oriented data

            Nested JSON:
            - Use flatten_keys to convert flat columns to nested paths
            - Dots in paths create nesting levels (e.g., 'info.address.street')
            - Columns not in flatten_keys become top-level keys
            - Particularly useful for GIS/location data

        Examples:
            CSV write mode (create new file):
                df = pd.DataFrame({'name': ['Alice', 'Bob'], 'age': [25, 30]})
                YFileUtils.write_df(df, 'output/people.csv', mode='w')

            CSV append mode (add rows to existing file):
                df_new = pd.DataFrame({'name': ['Charlie'], 'age': [35]})
                YFileUtils.write_df(df_new, 'output/people.csv', mode='a')

            JSON write mode (flat structure):
                YFileUtils.write_df(df, 'output/data.json', mode='w')

            JSON write mode (nested structure):
                flatten_keys = {
                    'latitude': 'location.coordinates.lat',
                    'longitude': 'location.coordinates.lon',
                    'street': 'location.address.street',
                    'city': 'location.address.city',
                    'postcode': 'location.address.postcode'
                }
                YFileUtils.write_df(df, 'output/locations.json',
                                  mode='w', flatten_keys=flatten_keys)

            Result structure would be:
            {
              "name": "Sydney Station",
              "location": {
                "coordinates": {
                  "lat": -33.87,
                  "lon": 151.21
                },
                "address": {
                  "street": "Central Station",
                  "city": "Sydney",
                  "postcode": "2000"
                }
              }
            }

        Performance:
            - CSV: Linear time proportional to number of rows
            - JSON: Linear time with slight overhead for nesting
            - Memory: Proportional to DataFrame size (entire DF loaded)
            - Suitable for datasets up to several GB on modern hardware
        """
        # Create parent directories for output file
        YFileUtils.create_dir_if_not_exist(file_name)
        file_path = Path(file_name)

        # Route to appropriate writer based on file extension
        if file_path.suffix.lower() == '.csv':
            YFileUtils._write_csv(df, file_name, mode)
        elif file_path.suffix.lower() == '.json':
            YFileUtils._write_json(df, file_name, mode, flatten_keys)
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}. Supported formats: .csv, .json")

    @staticmethod
    def _write_csv(df: pd.DataFrame, file_name: str, mode: str = 'w') -> None:
        """Write DataFrame to CSV file with intelligent append mode handling.

        Internal method called by write_df() for CSV output. Handles both write
        and append modes with automatic header management.

        Args:
            df (pd.DataFrame): DataFrame to write as CSV.

            file_name (str): Path to CSV file.

            mode (str): Write mode - 'w' (write/overwrite) or 'a' (append).
                       Defaults to 'w'.

        Returns:
            None

        Implementation Details:
            - Write mode ('w'): Creates new file or overwrites existing, includes header
            - Append mode ('a'): Appends rows to existing file, omits header to prevent
                               duplication and maintain CSV format integrity
            - Index is never written (uses index=False)
            - NaN values become empty strings in CSV
            - All columns are included in output

        Note:
            - This is an internal method, use write_df() instead
            - Append mode with non-existent file falls back to write mode
            - No validation of existing file structure during append
        """
        file_path = Path(file_name)

        if mode == 'a' and file_path.exists():
            # Append mode: write without header to avoid duplication
            # Assumes existing file has compatible structure
            df.to_csv(file_name, mode='a', header=False, index=False)
        else:
            # Write mode: create new file or overwrite existing with header
            df.to_csv(file_name, mode='w', index=False)

    @staticmethod
    def _write_json(df: pd.DataFrame, file_name: str, mode: str = 'w',
                    flatten_keys: Optional[Dict[str, str]] = None) -> None:
        """Write DataFrame to JSON file with optional nesting and append support.

        Internal method called by write_df() for JSON output. Converts DataFrame
        rows to JSON records with optional nesting via flatten_keys.

        Args:
            df (pd.DataFrame): DataFrame to write as JSON.

            file_name (str): Path to JSON file.

            mode (str): Write mode - 'w' (write/overwrite) or 'a' (append).
                       Defaults to 'w'.

            flatten_keys (Dict[str, str], optional): Mapping of column names to
                                                     nested JSON paths for
                                                     unflattening. Defaults to None
                                                     (produces flat JSON).

        Returns:
            None

        Implementation Details:
            - DataFrame rows converted to list of dicts (JSON records)
            - NaN values automatically excluded from output (cleaner JSON)
            - Write mode: creates new file or overwrites existing
            - Append mode: reads existing data and extends the array
            - Handles both single-object and array JSON structures
            - Pretty-printed with 2-space indentation
            - Uses default=str for non-standard types (e.g., datetime)

        Data Conversion:
            - Each DataFrame row becomes a JSON object
            - Column names become JSON keys
            - NaN/None values are filtered out (not written as null)
            - Non-serializable types converted to string representation
            - Numeric types preserved as numbers (not quoted)
            - String types preserve formatting and special characters

        Append Mode Behavior:
            - Reads existing JSON file
            - Detects if root is single object or array
            - Converts single object to array if needed
            - Extends array with new records
            - Maintains JSON validity

        Note:
            - This is an internal method, use write_df() instead
            - Append to non-existent file falls back to write mode
            - JSON output always uses 2-space indentation for readability

        Performance:
            - Append mode requires reading entire JSON file
            - Suitable for moderate-sized JSON files (< 1GB)
            - Memory usage proportional to file size during append
        """
        import json

        file_path = Path(file_name)

        # Step 1: Convert DataFrame to list of record dicts
        if flatten_keys:
            # Use unflattening to create nested structures
            records = YFileUtils._unflatten_records(df, flatten_keys)
        else:
            # Standard flat JSON records, excluding NaN values
            records = [
                {k: v for k, v in row.items() if pd.notna(v)}
                for row in df.to_dict(orient='records')
            ]

        # Step 2: Handle append mode by reading existing data
        if mode == 'a' and file_path.exists():
            with open(file_name, 'r') as f:
                existing_data = json.load(f)

            # Handle both array and single-object JSON structures
            if isinstance(existing_data, list):
                # Existing data is array: extend it
                existing_data.extend(records)
            else:
                # Existing data is single object: convert to array and add
                existing_data = [existing_data] + records
        else:
            # Write mode: start fresh
            existing_data = records

        # Step 3: Write to file with pretty printing
        with open(file_name, 'w') as f:
            # indent=2: human-readable formatting
            # default=str: convert non-JSON types to string representation
            json.dump(existing_data, f, indent=2, default=str)

    @staticmethod
    def _unflatten_records(df: pd.DataFrame, flatten_keys: Dict[str, str]) -> list:
        """Convert flat DataFrame columns to nested JSON/dict structure.

        Transforms a flat DataFrame (typical CSV-like structure) into nested
        dictionary structures for JSON output. Useful for converting tabular
        data to hierarchical formats.

        Args:
            df (pd.DataFrame): Flattened DataFrame with columns to be nested.
                             Typically from CSV or relational database.

            flatten_keys (Dict[str, str]): Mapping of DataFrame column names to
                                          nested JSON paths using dot notation.
                                          Examples:
                                          - 'latitude' → 'location.coordinates.lat'
                                          - 'longitude' → 'location.coordinates.lon'
                                          - 'street' → 'location.address.street'
                                          - 'name' → 'info.name'

        Returns:
            list: List of nested dictionaries, one per DataFrame row.
                 Columns in flatten_keys are placed at specified nested paths.
                 Columns not in flatten_keys remain as top-level keys.
                 NaN values are excluded from all levels.

        Nesting Algorithm:
            1. Each DataFrame row becomes one dict
            2. For each column value:
               a. If NaN: skip (exclude from output)
               b. If in flatten_keys: navigate path, create intermediate dicts, set value
               c. If not in flatten_keys: add as top-level key
            3. Return list of all nested dicts

        Path Navigation:
            - Paths use dot notation: 'a.b.c' creates {'a': {'b': {'c': value}}}
            - Intermediate dicts auto-created if not present
            - Existing dicts reused to preserve previous values
            - Final key in path receives the actual value

        NaN Handling:
            - All NaN values excluded completely (not even null placeholders)
            - Results in compact JSON without empty/null fields
            - Particularly important for optional/sparse data

        Column Handling:
            - Columns in flatten_keys: moved to nested path
            - Columns not in flatten_keys: remain as top-level keys
            - Order doesn't matter; all columns processed
            - Works with any column name (underscores, spaces, etc.)

        Examples:
            Input DataFrame:
                id  name   latitude   longitude   street              city
                1   'Pt1'  -33.8688   151.2093    'Sydney Rd'        'Sydney'
                2   'Pt2'  -37.8136   144.9631    'Collins St'       'Melbourne'

            flatten_keys = {
                'latitude': 'location.coordinates.lat',
                'longitude': 'location.coordinates.lon',
                'street': 'location.address.street',
                'city': 'location.address.city'
            }

            Output:
            [
                {
                    "id": 1,
                    "name": "Pt1",
                    "location": {
                        "coordinates": {"lat": -33.8688, "lon": 151.2093},
                        "address": {"street": "Sydney Rd", "city": "Sydney"}
                    }
                },
                {
                    "id": 2,
                    "name": "Pt2",
                    "location": {
                        "coordinates": {"lat": -37.8136, "lon": 144.9631},
                        "address": {"street": "Collins St", "city": "Melbourne"}
                    }
                }
            ]

        Use Cases:
            - Converting GIS/location data from CSV to GeoJSON-like structure
            - Transforming flat database exports to hierarchical API responses
            - Restructuring flat measurement data with metadata
            - Converting tabular data to document-oriented formats

        Performance:
            - Time: O(n × m) where n=rows, m=columns (linear in data size)
            - Memory: O(n × output_size) for nested structures
            - Suitable for datasets with thousands of rows
            - For very large datasets (millions+), consider batch processing

        Note:
            - This is an internal method, use write_df() with flatten_keys instead
            - Empty paths (keys[:-1] is empty) not possible with dot notation
            - Leading/trailing dots in paths cause empty string keys (avoid)
        """
        records = []

        # Process each row of the DataFrame
        for _, row in df.iterrows():
            record = {}

            # Process each column
            for col in df.columns:
                value = row[col]

                # Skip NaN/None values entirely (exclude from output)
                if pd.isna(value):
                    continue

                # Route column to appropriate location (nested or top-level)
                if col in flatten_keys:
                    # This column should be nested at specified path
                    nested_path = flatten_keys[col]
                    keys = nested_path.split('.')

                    # Navigate/create nested structure using path
                    # For 'a.b.c', create {'a': {'b': {'c': value}}}
                    current = record
                    for key in keys[:-1]:
                        # Auto-create intermediate dicts if needed
                        if key not in current:
                            current[key] = {}
                        current = current[key]

                    # Set value at final key
                    current[keys[-1]] = value
                else:
                    # This column stays at top level
                    record[col] = value

            records.append(record)

        return records
