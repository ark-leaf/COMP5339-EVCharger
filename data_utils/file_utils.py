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

    All methods are static and can be called directly on the class without instantiation.
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
        """
        # Create extraction directory and any parent directories
        YFileUtils.create_dir_if_not_exist(extract_dir_path)

        # Open ZIP file and extract all contents
        with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
            # extractall() preserves the directory structure from inside the ZIP
            zip_ref.extractall(extract_dir_path)

    @staticmethod
    def write_df(df: pd.DataFrame, file_name: str, mode: str = 'w',
                 flatten_keys: Optional[Dict[str, str]] = None, header: bool = True,
                 format: Optional[str] = None) -> None:
        """Write DataFrame to CSV or JSON file with flexible formatting options.

        Writes a pandas DataFrame to either CSV or JSON format with intelligent format
        detection and explicit format override support.

        Args:
            df (pd.DataFrame): DataFrame containing the data to write.
                             All data types are handled automatically.

            file_name (str): Output file path.
                           When format=None, extension determines output format.
                           When format is specified, used regardless of extension.
                           Parent directories are created automatically.
                           Examples:
                           - 'output/data.csv'
                           - 'results/locations.json'
                           - 'data' (no extension, defaults to CSV if format=None)

            mode (str, optional): Write mode. Defaults to 'w'.
                                 - 'w': Write mode (create new or overwrite existing)
                                 - 'a': Append mode (add data to existing file)
                                        For CSV: new rows are appended without header
                                        For JSON: new records are added to array

            flatten_keys (Dict[str, str], optional): For JSON output only.
                                                     Maps flat DataFrame column names
                                                     to nested JSON paths.
                                                     Defaults to None (flat JSON).
                                                     Example: {'lat': 'location.lat',
                                                               'lon': 'location.lon'}

            header (bool, optional): For CSV output only. Defaults to True.
                                    - True: Include column names as header row
                                    - False: Write only data rows without header
                                    Note: Append mode automatically sets header=False

            format (str, optional): Explicit output format. Defaults to None.
                                   - None: Auto-detect from file extension
                                           If no extension or unknown, defaults to 'csv'
                                   - 'csv': Force CSV format
                                   - 'json': Force JSON format
                                   Examples:
                                   - format=None, 'data' → CSV (no extension)
                                   - format=None, 'data.csv' → CSV (from extension)
                                   - format=None, 'data.dat' → CSV (unknown extension)
                                   - format=None, 'data.json' → JSON (from extension)
                                   - format='csv', 'data.json' → CSV (override)
                                   - format='json', 'data.csv' → JSON (override)

        Returns:
            None

        Raises:
            ValueError: If file extension is not .csv or .json.
            IOError: If file cannot be written (permission denied, disk full, etc.).
            TypeError: If DataFrame contains non-serializable data types in JSON mode.
        """
        # Create parent directories for output file
        YFileUtils.create_dir_if_not_exist(file_name)
        file_path = Path(file_name)

        # Determine output format
        if format is not None:
            # Use explicit format if provided
            output_format = format.lower()
        else:
            # Auto-detect from file extension, default to CSV for missing/unknown
            ext = file_path.suffix.lower()
            if ext == '.json':
                output_format = 'json'
            else:
                # Default to CSV for no extension, unknown extension, or .csv
                output_format = 'csv'

        # Route to appropriate writer based on determined format
        if output_format == 'csv':
            YFileUtils._write_csv(df, file_name, mode, header)
        elif output_format == 'json':
            YFileUtils._write_json(df, file_name, mode, flatten_keys)
        else:
            raise ValueError(f"Unsupported format: '{format}'. Supported formats: 'csv', 'json'")

    @staticmethod
    def _write_csv(df: pd.DataFrame, file_name: str, mode: str = 'w',
                   header: bool = True) -> None:
        """Write DataFrame to CSV file with intelligent append mode handling.

        Internal method called by write_df() for CSV output. Handles both write
        and append modes with flexible header control.

        Args:
            df (pd.DataFrame): DataFrame to write as CSV.

            file_name (str): Path to CSV file.

            mode (str): Write mode - 'w' (write/overwrite) or 'a' (append).
                       Defaults to 'w'.

            header (bool): Whether to include column names as first row.
                          Defaults to True.
                          - Write mode: respects this parameter
                          - Append mode: automatically set to False to prevent duplication

        Returns:
            None
        """
        file_path = Path(file_name)

        if mode == 'a' and file_path.exists():
            # Append mode: always write without header to avoid duplication
            # Assumes existing file has compatible structure
            # Ignores header parameter to maintain CSV integrity
            df.to_csv(file_name, mode='a', header=False, index=False)
        else:
            # Write mode: create new file or overwrite existing
            # Respects header parameter
            df.to_csv(file_name, mode='w', header=header, index=False)

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
    def _unflatten_dict(flat_dict: Dict[str, Any], flatten_keys: Dict[str, str]) -> dict:
        """Convert a single flat dictionary to nested structure using flatten_keys mapping.

        Helper function for _unflatten_records. Transforms one flat dict by moving
        specified keys to nested paths while preserving other keys at top level.

        Args:
            flat_dict (Dict[str, Any]): Single row dict from DataFrame.to_dict(orient='records').
                                       May contain NaN values.

            flatten_keys (Dict[str, str]): Mapping of flat keys to nested paths.
                                          e.g., {'lat': 'location.lat', 'lon': 'location.lon'}

        Returns:
            dict: Nested dictionary with some keys moved to nested paths.
                 NaN values excluded entirely.
        """
        nested_dict = {}

        for col, value in flat_dict.items():
            # Skip NaN/None values entirely
            if pd.isna(value):
                continue

            # Route to nested or top-level location
            if col in flatten_keys:
                nested_path = flatten_keys[col]
                YFileUtils._set_nested_value(nested_dict, nested_path, value)
            else:
                nested_dict[col] = value

        return nested_dict

    @staticmethod
    def _set_nested_value(d: dict, path: str, value: Any) -> None:
        """Set a value in a nested dictionary using dot-notation path.

        Helper function to navigate/create nested structure. Modifies dict in-place.

        Args:
            d (dict): Dictionary to modify (modified in-place).

            path (str): Dot-separated path (e.g., 'location.coordinates.lat').
                       Each dot creates a nesting level.

            value (Any): Value to set at the final key.

        Example:
            d = {}
            _set_nested_value(d, 'a.b.c', 42)
            # Result: d = {'a': {'b': {'c': 42}}}
        """
        keys = path.split('.')
        current = d

        # Navigate/create nested structure for all intermediate keys
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # Set value at final key
        current[keys[-1]] = value

    @staticmethod
    def _unflatten_records(df: pd.DataFrame, flatten_keys: Dict[str, str]) -> list:
        """Convert flat DataFrame columns to nested JSON/dict structure.

        Transforms a flat DataFrame (typical CSV-like structure) into nested
        dictionary structures for JSON output. Uses pandas to_dict() for efficiency.

        Args:
            df (pd.DataFrame): Flattened DataFrame with columns to be nested.
                             Typically from CSV or relational database.

            flatten_keys (Dict[str, str]): Mapping of DataFrame column names to
                                          nested JSON paths using dot notation.

        Returns:
            list: List of nested dictionaries, one per DataFrame row.
                 Columns in flatten_keys are placed at specified nested paths.
                 Columns not in flatten_keys remain as top-level keys.
                 NaN values are excluded from all levels.
        """
        # Step 1: Use pandas efficient vectorized to_dict() instead of iterrows()
        # to_dict(orient='records') returns list of dicts, one per row
        # This is much faster than iterating with iterrows()
        flat_records = df.to_dict(orient='records')

        # Step 2: Transform each flat record to nested structure
        # Map _unflatten_dict over all records using list comprehension
        records = [
            YFileUtils._unflatten_dict(record, flatten_keys)
            for record in flat_records
        ]

        return records
