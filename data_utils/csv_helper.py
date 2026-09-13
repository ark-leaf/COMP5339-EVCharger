import os
from typing import Iterator

import pandas as pd

from data_utils.file_helper import FileHelper

DEFAULT_OUTPUT_CSV_FILE = './default_output.csv'


class CsvHelper(FileHelper):
    """
    A helper class for processing CSV files.

    This class extends `FileHelper` to provide specific implementations for
    reading and writing data from and to CSV files. It supports reading
    files in chunks and writing data with or without a header.
    """

    def __init__(self, input_file_name: str,
                 output_file_name: str = DEFAULT_OUTPUT_CSV_FILE,
                 chunk_size: int = None,
                 columns: list[str] = None):
        """
        Initializes the CsvHelper.

        :param input_file_name: The name of the input CSV file.
        :param output_file_name: The name of the output CSV file.
        :param chunk_size: The size of chunks to read from the file. The whole file will be load if it's None
        :param columns: A list of columns to read from the file. All columns will be load if it's None
        """
        super().__init__(input_file_name, output_file_name, chunk_size, columns)
        self.i = 0

    def read_file(self) -> Iterator[pd.DataFrame]:
        """
        Reads the input CSV file in chunks.

        :return: A generator that yields DataFrames for each chunk.
        """
        if self.chunk_size is None:
            yield pd.read_csv(self.input_file_name, usecols=self.columns)
        else:
            with pd.read_csv(self.input_file_name, chunksize=self.chunk_size, usecols=self.columns) as reader:
                for one_chunk in reader:
                    yield one_chunk

    def write_file(self, df: pd.DataFrame):
        """
        Writes a DataFrame to the output CSV file.

        If it's the first write, it will create the file and write the header.
        Subsequent writes will append to the file without the header.

        :param df: The DataFrame to write.
        """
        if self._is_first_write:
            if os.path.exists(self.output_file_name):
                os.remove(self.output_file_name)
            df.to_csv(self.output_file_name, mode='w', header=True, index=False)
            self._is_first_write = False
            self.i += len(df)
        else:
            df.to_csv(self.output_file_name, mode='a', header=False, index=False)
            self.i += len(df)
