"""File utility operations for data processing.

This module provides utilities for file operations including downloading files,
extracting archives, writing DataFrames to various formats with support
for append modes and nested JSON structures, and reading various geospatial and data formats.
"""
import json
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any, Union, Iterator

import geopandas as gpd
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
                 flatten_keys: Optional[Dict[str, str]] = None, header: bool = True) -> None:
        """Write DataFrame to CSV or JSON file with flexible formatting options.

        Writes a pandas DataFrame to either CSV or JSON format, determined by the
        file extension. Supports both write (overwrite) and append modes.

        Args:
            df (pd.DataFrame): DataFrame containing the data to write.

            file_name (str): Output file path with extension (.csv or .json).
                           Determines the output format.
                           Parent directories are created automatically.
                           Examples:
                           - 'output/data.csv'
                           - 'results/locations.json'

            mode (str, optional): Write mode. Defaults to 'w'.
                                 - 'w': Write mode (create new or overwrite existing)
                                 - 'a': Append mode (add data to existing file)
                                        For CSV: new rows appended without header
                                        For JSON: new records added to array

            flatten_keys (Dict[str, str], optional): For JSON output only.
                                                     Maps flat DataFrame column names
                                                     to nested JSON paths.
                                                     Defaults to None (flat JSON).
                                                     Example: {'lat': 'location.coordinates.lat',
                                                               'lon': 'location.coordinates.lon'}

            header (bool, optional): For CSV output only. Defaults to True.
                                    - True: Include column names as header row
                                    - False: Write only data rows without header
                                    Note: Append mode automatically sets header=False

        Returns:
            None

        Raises:
            ValueError: If file extension is not .csv or .json.
            IOError: If file cannot be written (permission denied, disk full, etc.).
        """
        # Create parent directories for output file
        YFileUtils.create_dir_if_not_exist(file_name)
        file_path = Path(file_name)

        # Determine format from file extension
        if file_path.suffix.lower() == '.csv':
            YFileUtils._write_csv(df, file_name, mode, header)
        elif file_path.suffix.lower() == '.json':
            YFileUtils._write_json(df, file_name, mode, flatten_keys)
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}. Supported formats: .csv, .json")

    @staticmethod
    def _write_csv(df: pd.DataFrame, file_name: str, mode: str = 'w', header: bool = True) -> None:
        """Write DataFrame to CSV file with append mode support."""
        file_path = Path(file_name)

        if mode == 'a' and file_path.exists():
            # Append mode: write without header to avoid duplication
            df.to_csv(file_name, mode='a', header=False, index=False)
        else:
            # Write mode: respects header parameter
            df.to_csv(file_name, mode='w', header=header, index=False)

    @staticmethod
    def _write_json(df: pd.DataFrame, file_name: str, mode: str = 'w',
                    flatten_keys: Optional[Dict[str, str]] = None) -> None:
        """Write DataFrame to JSON file with optional nested structure and append support."""
        file_path = Path(file_name)

        # Convert DataFrame to records using efficient to_dict()
        if flatten_keys:
            # Transform each flat record to nested structure
            flat_records = df.to_dict(orient='records')
            records = []
            for record in flat_records:
                nested_dict = {}
                for col, value in record.items():
                    # Skip NaN values
                    if pd.isna(value):
                        continue

                    # Route to nested or top-level location
                    if col in flatten_keys:
                        # Navigate/create nested structure using dot-notation path
                        nested_path = flatten_keys[col]
                        keys = nested_path.split('.')
                        current = nested_dict
                        for key in keys[:-1]:
                            if key not in current:
                                current[key] = {}
                            current = current[key]
                        current[keys[-1]] = value
                    else:
                        # Top-level column
                        nested_dict[col] = value
                records.append(nested_dict)
        else:
            # Flat JSON records, excluding NaN values
            records = [
                {k: v for k, v in row.items() if pd.notna(v)}
                for row in df.to_dict(orient='records')
            ]

        # Handle append mode
        if mode == 'a' and file_path.exists():
            with open(file_name, 'r') as f:
                existing_data = json.load(f)

            # Handle both array and single-object JSON structures
            if isinstance(existing_data, list):
                existing_data.extend(records)
            else:
                existing_data = [existing_data] + records
        else:
            existing_data = records

        # Write to file
        with open(file_name, 'w') as f:
            json.dump(existing_data, f, indent=2, default=str)

    @staticmethod
    def read_file(file_name: str, format: str = 'csv', chunk_size: int = -1) -> Union[pd.DataFrame, Iterator[pd.DataFrame]]:
        """Read data from CSV, JSON, or GPKG file formats.

        Supports multiple file formats with optional chunking for large files.
        Format is auto-detected from file extension if not specified.

        Args:
            file_name (str): Path to the file to read.
                           Must be a valid CSV, JSON, or GPKG file.
                           Examples:
                           - 'data/input.csv'
                           - 'data/locations.json'
                           - 'data/geodata.gpkg'

            format (str, optional): Output format. Defaults to 'csv'.
                                   - 'csv': Read CSV file
                                   - 'json': Read JSON file
                                   - 'gpkg': Read GeoPackage file (requires geopandas)
                                   - 'auto': Auto-detect from file extension
                                   When auto-detecting: .csv → CSV, .json → JSON,
                                   .gpkg → GPKG, others default to CSV

            chunk_size (int, optional): Number of rows to read per chunk. Defaults to -1.
                                       - -1: Read entire file at once (returns DataFrame)
                                       - > 0: Read in chunks (returns Iterator[DataFrame])
                                             Useful for large files that don't fit in memory
                                       Note: JSON chunking reads entire file and yields chunks

        Returns:
            Union[pd.DataFrame, Iterator[pd.DataFrame]]:
            - If chunk_size == -1: Returns a single DataFrame with all data
            - If chunk_size > 0: Returns an iterator yielding DataFrames of chunk_size rows
                                Each chunk is a separate DataFrame except for JSON
                                (JSON reads entire file and yields chunks from memory)

        Raises:
            FileNotFoundError: If the file doesn't exist at the specified path.
            ValueError: If the format is unsupported or file extension is unrecognized.
            ImportError: If trying to read GPKG without geopandas installed.
            json.JSONDecodeError: If JSON file is malformed.

        Note:
            CSV Mode:
            - Handles NaN and missing values automatically
            - First row treated as header
            - Chunking creates an iterator for memory-efficient reading

            JSON Mode:
            - Expects JSON to be an array of objects (records format)
            - If chunking: reads entire file, yields chunks from memory
            - Each chunk is a DataFrame of chunk_size rows

            GPKG Mode:
            - GeoPackage is a spatial database format (SQLite + GIS extensions)
            - Requires geopandas library (install: pip install geopandas)
            - Returns GeoDataFrame with geometry column
            - Chunking not recommended (reads all geometries into memory)

        Examples:
            Read entire CSV file:
                df = YFileUtils.read_file('data.csv')

            Read CSV file in chunks (for large files):
                for chunk_df in YFileUtils.read_file('large_data.csv', chunk_size=1000):
                    process_chunk(chunk_df)

            Read JSON file:
                df = YFileUtils.read_file('data.json', format='json')

            Read GeoPackage file:
                gdf = YFileUtils.read_file('geodata.gpkg', format='gpkg')

            Auto-detect format from extension:
                df = YFileUtils.read_file('data.csv', format='auto')  # detects CSV
                gdf = YFileUtils.read_file('geodata.gpkg', format='auto')  # detects GPKG

        Performance:
            - CSV: Linear time in file size, memory depends on chunk_size
            - JSON: Linear time, loads entire file into memory
            - GPKG: Varies with spatial operations, database query time
            - Chunking CSV: Memory-efficient for large datasets (1GB+)
        """
        file_path = Path(file_name)

        # Auto-detect format from extension if 'auto' is specified
        if format.lower() == 'auto':
            ext = file_path.suffix.lower()
            if ext == '.json':
                format = 'json'
            elif ext == '.gpkg':
                format = 'gpkg'
            else:
                # Default to CSV for no extension, unknown extension, or .csv
                format = 'csv'

        # Route to appropriate reader based on format
        if format.lower() == 'csv':
            return YFileUtils._read_csv(file_name, chunk_size)
        elif format.lower() == 'json':
            return YFileUtils._read_json(file_name, chunk_size)
        elif format.lower() == 'gpkg':
            return YFileUtils._read_gpkg(file_name, chunk_size)
        else:
            raise ValueError(f"Unsupported format: '{format}'. Supported formats: 'csv', 'json', 'gpkg', 'auto'")

    @staticmethod
    def _read_csv(file_name: str, chunk_size: int = -1) -> Union[pd.DataFrame, Iterator[pd.DataFrame]]:
        """Read CSV file with optional chunking."""
        if chunk_size <= 0:
            # Read entire file at once
            return pd.read_csv(file_name)
        else:
            # Read in chunks, return iterator
            return pd.read_csv(file_name, chunksize=chunk_size)

    @staticmethod
    def _read_json(file_name: str, chunk_size: int = -1) -> Union[pd.DataFrame, Iterator[pd.DataFrame]]:
        """Read JSON file with optional chunking.

        JSON format expected to be an array of objects (records).
        """
        # Load entire JSON file (since JSON structure must be complete)
        with open(file_name, 'r') as f:
            data = json.load(f)

        # Convert to DataFrame
        df = pd.DataFrame(data)

        if chunk_size <= 0:
            # Return entire DataFrame
            return df
        else:
            # Create iterator that yields chunks
            def chunk_iterator():
                for i in range(0, len(df), chunk_size):
                    yield df.iloc[i:i + chunk_size]

            return chunk_iterator()

    @staticmethod
    def _read_gpkg(file_name: str, chunk_size: int = -1) -> Union[pd.DataFrame, Iterator[pd.DataFrame]]:
        """Read GeoPackage file using geopandas."""
        # Read GeoPackage file
        gdf = gpd.read_file(file_name)

        if chunk_size <= 0:
            # Return entire GeoDataFrame
            return gdf
        else:
            # Create iterator that yields chunks
            def chunk_iterator():
                for i in range(0, len(gdf), chunk_size):
                    yield gdf.iloc[i:i + chunk_size]

            return chunk_iterator()
