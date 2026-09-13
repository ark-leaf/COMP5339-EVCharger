import numpy as np
import pandas as pd

from data_utils.column_cleaner import ColumnCleaner, DFDataType

# Load the source dirty data from which CSV file:
DIRTY_DATA_FILE_NAME = 'rice-final2.csv'

# Write the clean data to which CSV file:
CLEAN_DATA_FILE_NAME = 'rice-clean.csv'

# How many rows of data to be cleaned each time?
#  - CAUTIOUS: The bigger the CHUNK_SIZE you set, the more memory space may require.
CHUNK_SIZE = 2000

# Config the data cleaners for each column of the dataset:

# # - Numerical feature processor
# POST_PROCESS_PIPELINE = Pipeline([
#     # Fill NaN with the mean value of current column
#     ("imputer", SimpleImputer(missing_values=np.nan, strategy='mean')),
#     # Normalize the current column
#     ("scaler", MinMaxScaler(feature_range=(0, 1))),
# ])

def df_numerical_processor(df: pd.DataFrame) -> pd.DataFrame:
    POST_PROCESS_PIPELINE.set_output(transform='pandas')
    df = POST_PROCESS_PIPELINE.fit_transform(df)
    return df

def col_numerical_processor(col_series: pd.Series) -> pd.Series:
    POST_PROCESS_PIPELINE.set_output(transform='pandas')
    col_series = POST_PROCESS_PIPELINE.fit_transform(col_series)
    return col_series


# - Cleaners
COLUMN_CLEANERS = [
    # The Dependent Variable
    ColumnCleaner(
        'class',
        DFDataType.CATEGORY,
        special_values={
            'class1': 0,
            'class2': 1,
        },
    ),
    # The Independent Variables
    ColumnCleaner(
        'Area',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    ColumnCleaner(
        'Perimiter',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    ColumnCleaner(
        'Major_Axis_Length',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    ColumnCleaner(
        'Minor_Axis_Length',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    ColumnCleaner(
        'Eccentricity',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    ColumnCleaner(
        'Convex_Area',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    ColumnCleaner(
        'Extent',
        DFDataType.FLOAT,
        special_values={
            '?': np.nan,
        },
        post_processor=col_numerical_processor
    ),
    # Instruction of using Ye's data processing pipeline:
    # - Create Columns:
    #
    # ColumnCleaner(
    #     # New column's name:
    #     'example_column_name',
    #     # New column's data type:
    #     DFDataType.INT, # New column's datatype
    #     # New column's creating method; the argument "df" is the whole pandas.DataFrame:
    #     column_create_function=lambda df: df['stays_in_weekend_nights'] + df['stays_in_week_nights']
    # ),
    #
    # - Remove Column

]
