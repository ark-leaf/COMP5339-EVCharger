"""File utility operations for data processing.

This module provides utilities for file operations including downloading files
and reading various geospatial and data formats.
"""
import csv
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Union, Iterator

import geopandas as gpd
import pandas as pd
import requests

# Configure logging for file operations
logger = logging.getLogger(__name__)


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
    def download_file(url: str, output_file_name: str, override: bool = True) -> None:
        """Download a file from a URL and save it to local storage.

        Downloads files using HTTP with streaming to handle large files efficiently
        without loading entire file into memory. Creates parent directories if needed.

        Args:
            url (str): URL of the file to download. Must be a valid HTTP(S) URL.
                      Example: 'https://example.com/data/file.csv'

            output_file_name (str): Local file path where the downloaded file will be saved.
                                   Parent directories will be created automatically.
                                   Example: 'data/downloaded/file.csv'

            override (bool, optional): Whether to download and overwrite if file already exists.
                                      Defaults to True.
                                      - True: Download and overwrite existing file
                                      - False: Skip download if file exists, just log message

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

        # Check if file exists and override is False
        if Path(output_file_name).exists() and not override:
            YFileUtils._validate_download(Path(output_file_name), Path(output_file_name).suffix)
            logger.info(f"File {output_file_name} exists")
            print(f"File {output_file_name} exists")
            return

        # Stream the file from URL to local storage
        print(f"Start downloading from: {url}")
        destination = Path(output_file_name)
        temporary = None
        try:
            with requests.get(url, stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".part", delete=False) as file:
                    temporary = Path(file.name)
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
            # Validate the bytes, not Content-Type: TfNSW labels its CSV as Excel.
            YFileUtils._validate_download(temporary, destination.suffix)
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        print(f"Finish downloading from: {url}")
        print(f"File has been saved to: {output_file_name}")

    @staticmethod
    def _validate_download(path: Path, suffix: str) -> None:
        """Reject empty files, error pages and corrupt source archives."""
        if path.stat().st_size == 0:
            raise ValueError(f"Empty source file: {path}")
        if suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                if not archive.namelist() or archive.testzip() is not None:
                    raise ValueError(f"Invalid source archive: {path}")
        elif suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                start = stream.read(512).lstrip().lower()
                if start.startswith(("<!doctype html", "<html", "<?xml")):
                    raise ValueError(f"Expected CSV, received a web page: {path}")
                stream.seek(0)
                header = next(csv.reader(stream), [])
                if len(header) < 2:
                    raise ValueError(f"Invalid source CSV header: {path}")

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
