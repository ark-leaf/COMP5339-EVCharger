import zipfile
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

class YFileUtils:
    @staticmethod
    def create_dir_if_not_exist(dir_path):
        file_path = Path(dir_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def download_file(url, output_file_name):
        YFileUtils.create_dir_if_not_exist(output_file_name)
        # Download the file
        with requests.get(url, stream=True) as response:
            response.raise_for_status()  # Raise error for bad responses (404, 500)

            # Open file and write chunks sequentially. Override it if the file exists
            with open(output_file_name, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # Filter out keep-alive new chunks
                        file.write(chunk)
    @staticmethod
    def unzip_file(zip_file_path, extract_dir_path):
        YFileUtils.create_dir_if_not_exist(extract_dir_path)
        with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir_path)

    @staticmethod
    def write_df(df: pd.DataFrame, file_name: str, mode='w', flatten_keys=None):
        """Write DataFrame to CSV or JSON file with append mode support.

        Args:
            df: DataFrame to write
            file_name: Output file path (determines format from extension: .csv or .json)
            mode: 'w' for write (overwrite), 'a' for append
            flatten_keys: For JSON with nested structure, dict mapping column name to nested keys
                         e.g. {'address': 'location.address', 'lat': 'location.lat'}
                         This will unflatten the dataframe before writing

        Returns:
            None

        Examples:
            # CSV write/append
            YFileUtils.write_df(df, 'output.csv', mode='w')
            YFileUtils.write_df(df, 'output.csv', mode='a')

            # JSON write
            YFileUtils.write_df(df, 'output.json', mode='w')

            # JSON with nested structure (unflatten)
            YFileUtils.write_df(
                df, 'output.json', mode='w',
                flatten_keys={'lat': 'location.lat', 'lon': 'location.lon'}
            )
        """
        YFileUtils.create_dir_if_not_exist(file_name)
        file_path = Path(file_name)

        # Determine format from file extension
        if file_path.suffix.lower() == '.csv':
            YFileUtils._write_csv(df, file_name, mode)
        elif file_path.suffix.lower() == '.json':
            YFileUtils._write_json(df, file_name, mode, flatten_keys)
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}. Supported formats: .csv, .json")

    @staticmethod
    def _write_csv(df: pd.DataFrame, file_name: str, mode='w'):
        """Write DataFrame to CSV file with append support."""
        file_path = Path(file_name)

        if mode == 'a' and file_path.exists():
            df.to_csv(file_name, mode='a', header=False, index=False)
        else:
            df.to_csv(file_name, mode='w', index=False)

    @staticmethod
    def _write_json(df: pd.DataFrame, file_name: str, mode='w', flatten_keys=None):
        """Write DataFrame to JSON file with optional nested structure and append support."""
        import json

        file_path = Path(file_name)

        # Convert DataFrame to records
        if flatten_keys:
            records = YFileUtils._unflatten_records(df, flatten_keys)
        else:
            records = [
                {k: v for k, v in row.items() if pd.notna(v)}
                for row in df.to_dict(orient='records')
            ]

        if mode == 'a' and file_path.exists():
            with open(file_name, 'r') as f:
                existing_data = json.load(f)

            # Handle both list and single dict
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
    def _unflatten_records(df: pd.DataFrame, flatten_keys: dict):
        """Convert flattened DataFrame columns to nested JSON structure.

        Args:
            df: Flattened DataFrame
            flatten_keys: Dict mapping flat column names to nested paths
                         e.g. {'lat': 'location.lat', 'lon': 'location.lon', 'name': 'info.name'}

        Returns:
            List of dicts with nested structure
        """
        records = []

        for _, row in df.iterrows():
            record = {}

            for col in df.columns:
                value = row[col]
                # Skip NaN values
                if pd.isna(value):
                    continue

                # Check if column should be flattened
                if col in flatten_keys:
                    nested_path = flatten_keys[col]
                    keys = nested_path.split('.')
                    # Navigate/create nested structure
                    current = record
                    for key in keys[:-1]:
                        if key not in current:
                            current[key] = {}
                        current = current[key]
                    current[keys[-1]] = value
                else:
                    # Top-level column
                    record[col] = value

            records.append(record)

        return records
