from typing import Callable, Iterator

import geopandas as gpd
import pandas as pd

from data_utils.column_cleaner import ColumnCleaner
from data_utils.csv_file_helper import CsvFileHelper


class DataCleaner:
    def __init__(self,
                 column_cleaners: list[ColumnCleaner],
                 post_processor: Callable = None,
                 columns_to_keep: list[str] = None,
                 input_data_frame: pd.DataFrame = None,
                 input_file_name: str = None,
                 input_file_trunk_size: int = None,
                 output_file_name: str = None, ):
        self.column_cleaners: list[ColumnCleaner] = column_cleaners
        self.post_processor: Callable = post_processor
        self.columns_to_keep: list[str] | None = columns_to_keep
        self.input_data_frame = input_data_frame
        self.input_file_name = input_file_name
        self.input_file_trunk_size = input_file_trunk_size
        self.output_file_name = output_file_name
        self._file_helper = self._file_helper_initializer()

    def clean_data(self) -> pd.DataFrame | Iterator[pd.DataFrame]:
        if self.input_data_frame is not None:
            cleaned_df = self._clean_df(self.input_data_frame)
            self._file_helper.write_file(cleaned_df)
            return cleaned_df
        if self.input_file_name is not None:
            return self._clean_file_chunks()

    def _clean_file_chunks(self) -> Iterator[pd.DataFrame]:
        for one_chunk in self._mapper_csv_file():
            cleaned_chunk = self._clean_df(one_chunk)
            self._file_helper.write_file(cleaned_chunk)
            yield cleaned_chunk

    def _file_helper_initializer(self) -> CsvFileHelper | None:
        if self.input_file_name is None or self.output_file_name is None:
            return None
        return CsvFileHelper(self.input_file_name,
                             self.output_file_name,
                             self.input_file_trunk_size,
                             self.columns_to_keep)

    def _mapper_csv_file(self) -> Iterator[pd.DataFrame]:
        for one_chunk_df in self._file_helper.read_file():
            yield one_chunk_df

    def _clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        for one_cleaner in self.column_cleaners:
            one_cleaner.clean(df)
        if self.post_processor is not None:
            df = self.post_processor(df)
        return df
