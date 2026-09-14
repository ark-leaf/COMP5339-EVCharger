from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict

import pandas as pd

from data_utils.file_utils import YFileUtils

DEFAULT_OUTPUT_FILE_NAME = './file_helper_default_output'


class FileHelper(ABC):
    """
    An abstract base class for file processing helpers.

    This class provides a common interface for reading and writing data in chunks,
    allowing for efficient processing of large files. Subclasses should implement
    the `read_file` and `write_file` methods to handle specific file formats.
    """

    def __init__(self, _input_file_name: str, _output_file_name=DEFAULT_OUTPUT_FILE_NAME, _chunk_size: int = None,
                 _columns=None,):
        """
        Initializes the FileHelper.

        :param _input_file_name: The name of the input file.
        :param _output_file_name: The name of the output file.
        :param _chunk_size: The size of chunks to read from the file.
        :param _columns: A list of columns to read from the file.
        """
        super().__init__()
        self.input_file_name = _input_file_name
        self.output_file_name = _output_file_name
        self.chunk_size = _chunk_size
        self.columns = _columns
        self._is_first_write = True

    def download_input_file(self, url) -> FileHelper:
        YFileUtils.download_file(url, self.input_file_name)
        return self

    @abstractmethod
    def read_file(self) -> pd.DataFrame:
        """
        Reads the input file in chunks.

        :return: A generator that yields DataFrames for each chunk.
        """
        pass

    @abstractmethod
    def write_file(self, data: pd.DataFrame):
        """
        Writes a DataFrame to the output file.

        :param data: The DataFrame to write.
        """
        pass
