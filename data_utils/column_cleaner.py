from enum import Enum
from typing import Callable

import numpy as np
import pandas as pd
from pandas import DataFrame

DEFAULT_VALUE = np.nan
CATEGORICAL_DEFAULT_VALUE = np.nan
NUMERICAL_DEFAULT_VALUE = np.nan
STR_DEFAULT_VALUE = np.nan


class DFDataType(Enum):
    """
    An enumeration of supported data types for DataFrame columns.
    """
    CATEGORY = 'category'
    STR = 'object'
    INT = 'int64'
    FLOAT = 'float64'
    BOOL = 'bool'
    DATETIME = 'datetime64[us]'
    # DATETIME = 'datetime64[us]'


class ColumnCleaner:
    """
    A class for cleaning and transforming a specific column in a pandas DataFrame.

    This class provides a flexible way to handle missing values, special values,
    data type conversions, and other common data cleaning tasks. It can be
    configured to perform a variety of transformations, such as creating new
    columns, removing records, and renaming columns.
    """

    def __init__(self,
                 src_column_key: str,
                 data_type: DFDataType,
                 special_values: dict = {},
                 default_value=DEFAULT_VALUE,
                 rename_column_key: str = None,
                 column_create_function: Callable[[DataFrame], DataFrame] = None,
                 record_remove_index: int = None,
                 post_processor: Callable = None,
                 df_processor: Callable = None):
        """
        Initializes the ColumnCleaner.

        :param src_column_key: The key of the column to clean.
        :param data_type: The target data type of the column.
        :param special_values: A dictionary of special values to replace.
        :param default_value: The default value to use for missing data.
        :param rename_column_key: The new key to rename the column to.
        :param column_create_function: A function to create the column if it doesn't exist.
        :param record_remove_index: A function that returns a list of indices to remove.
        :param post_processor: A function applied to the column given the whole column data.
        :param df_processor: A function applied to the DataFrame given the whole DataFrame data.
        """
        self.src_column_key = src_column_key
        self.data_type = data_type
        self.special_values = special_values
        self.default_value = default_value
        self.rename_column_key = rename_column_key
        self.column_create_function = column_create_function
        self.record_remove_index = record_remove_index
        self.post_processor = post_processor
        self.df_processor = df_processor
        self._set_default_value(default_value)

    def _set_default_value(self, default_value):
        """
        Sets the default value based on the data type if no default is provided.
        """
        if default_value is not DEFAULT_VALUE:
            return
        if self.data_type is DFDataType.CATEGORY:
            self.default_value = CATEGORICAL_DEFAULT_VALUE
        elif self.data_type in [DFDataType.INT, DFDataType.FLOAT]:
            self.default_value = NUMERICAL_DEFAULT_VALUE
        elif self.data_type is DFDataType.STR:
            self.default_value = STR_DEFAULT_VALUE
        else:
            self.default_value = DEFAULT_VALUE

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Cleans and transforms the column in the given DataFrame.

        :param df: The DataFrame to clean.
        """
        # Create new column if required
        if self.column_create_function is not None:
            df[self.src_column_key] = self.column_create_function(df)
        # Remove records if required
        if self.record_remove_index is not None:
            for one_record_to_remove in self.record_remove_index(df):
                try:
                    df.drop(one_record_to_remove, inplace=True)
                except:
                    # Ignore the error: if we cannot find an invalid record in this trunk
                    pass

        # Set column type
        if df[self.src_column_key].dtype.name != self.data_type.value:
            df[self.src_column_key] = df[self.src_column_key].astype(self.data_type.value)

        # Trim white spaces if the data type is string
        if pd.api.types.is_string_dtype(df[self.src_column_key].dtype):
            df[self.src_column_key] = df[self.src_column_key].str.strip()

        # Fill NA / NaN with the default value
        df.fillna({self.src_column_key: self.default_value}, inplace=True)

        # Replace special values of the "bad guys"
        for specialValue in self.special_values.keys():
            df.loc[df[self.src_column_key] == specialValue, [self.src_column_key]] = self.special_values[specialValue]

        # Apply to column post processor if it's not None
        if self.post_processor is not None:
            df[self.src_column_key] = self.post_processor(df[[self.src_column_key]])

        # Apply to the whole df the df processor if it's not None
        if self.df_processor is not None:
            df = self.df_processor(df)

        # Change column name
        if self.rename_column_key is not None:
            df.rename(columns={self.src_column_key: self.rename_column_key}, inplace=True)
