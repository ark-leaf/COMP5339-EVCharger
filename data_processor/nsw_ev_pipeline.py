"""
Real-world DAG pipeline example: NSW EV Charging Data Processing

This pipeline demonstrates a complete data processing workflow:
1. Load raw CSV data
2. Apply data cleaning (normalization, type conversions)
3. Split into multiple analysis paths
4. Generate multiple reports

Pipeline structure:
                        ┌─→ validate_data ─────┐
    load_raw_data ──────┼─→ charger_analysis ───┼─→ merge_reports
                        ├─→ operator_summary ───┤
                        └─→ geographic_analysis ┘
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
from data_processor.task import Task
from data_processor.job import Job
from data_processor.job_runtime_local import JobRuntimeLocal
from config import NSW_EV_CHARGING_COLUMNS
from data_utils.data_cleaner import DataCleaner


# ============================================================================
# Pipeline Tasks
# ============================================================================

def load_raw_data():
    """Stage 1: Load raw NSW EV charging data from CSV."""
    print("  [1. load_raw_data] Loading nsw_ev_charging.csv...")
    df = pd.read_csv(
        'src_data/nsw_ev_charging.csv',
        usecols=[c.src_column_key for c in NSW_EV_CHARGING_COLUMNS]
    )
    print(f"    ✓ Loaded {len(df)} records, {len(df.columns)} columns")
    return df


def clean_data(raw_df):
    """Stage 2: Clean and normalize all columns."""
    print("  [2. clean_data] Cleaning and normalizing data...")
    df = raw_df.copy()

    # Use the configured data cleaners from config.py
    cleaner = DataCleaner(
        column_cleaners=NSW_EV_CHARGING_COLUMNS,
        input_data_frame=df
    )
    cleaner.clean_data()
    cleaned_df = cleaner.input_data_frame

    print(f"    ✓ Cleaned {len(cleaned_df)} records")
    print(f"    - Data types enforced")
    print(f"    - Missing values handled")
    print(f"    - Address normalized")
    return cleaned_df


def validate_data(cleaned_df):
    """Task 3a: Quality validation and flagging."""
    print("  [3a. validate_data] Validating data quality...")
    df = cleaned_df.copy()

    # Add validation flags
    df['has_station_name'] = df['Station_name'].notna()
    df['has_address'] = df['Station_address'].notna() & (df['Station_address'] != '')
    df['has_operator'] = df['Operator'].notna()
    df['is_upcoming'] = df['Charger_Type'] == 'Upcoming'
    df['is_complete'] = (
        df['has_station_name'] &
        df['has_operator'] &
        (df['Charger_Type'].isin(['AC', 'DC']))
    )

    complete_count = df['is_complete'].sum()
    upcoming_count = df['is_upcoming'].sum()

    print(f"    ✓ Validated {complete_count} complete records")
    print(f"    - {upcoming_count} upcoming (not yet built)")
    print(f"    - {(~df['is_complete']).sum()} incomplete")

    return df


def charger_analysis(cleaned_df):
    """Task 3b: Analyze charger distribution and capacity."""
    print("  [3b. charger_analysis] Analyzing charger types and capacity...")
    df = cleaned_df.copy()

    analysis = pd.DataFrame()

    # Charger type distribution
    charger_type_dist = df.groupby('Charger_Type').agg({
        'Number_of_plugs': ['count', 'sum', 'mean']
    }).round(1)
    charger_type_dist.columns = ['count', 'total_plugs', 'avg_plugs']
    charger_type_dist = charger_type_dist.reset_index()
    charger_type_dist = charger_type_dist.rename(
        columns={'Charger_Type': 'charger_type'}
    )

    # Rating distribution (only valid ratings)
    valid_ratings = df[df['Charger_rating'] != 'AC'].copy()
    rating_dist = valid_ratings['Charger_rating'].value_counts().head(10)

    print(f"    ✓ Charger type distribution:")
    for idx, row in charger_type_dist.iterrows():
        print(f"      {row['charger_type']:12s}: {int(row['count']):4d} stations, "
              f"{int(row['total_plugs']):5d} plugs")

    return charger_type_dist


def operator_summary(cleaned_df):
    """Task 3c: Summarize operator coverage."""
    print("  [3c. operator_summary] Analyzing operator coverage...")
    df = cleaned_df.copy()

    # Top operators
    operator_stats = df.groupby('Operator').agg({
        'Station_name': 'count',
        'Number_of_plugs': 'sum',
        'Charger_Type': lambda x: (x == 'DC').sum()
    }).sort_values('Number_of_plugs', ascending=False)

    operator_stats.columns = ['stations', 'total_plugs', 'dc_count']
    operator_stats = operator_stats.head(10).reset_index()

    print(f"    ✓ Top 10 operators by total plugs:")
    for idx, row in operator_stats.iterrows():
        print(f"      {row['Operator']:25s}: {row['stations']:3d} stations, "
              f"{int(row['total_plugs']):4d} plugs ({row['dc_count']:2d} DC)")

    return operator_stats


def geographic_analysis(cleaned_df):
    """Task 3d: Geographic distribution analysis."""
    print("  [3d. geographic_analysis] Analyzing geographic distribution...")
    df = cleaned_df.copy()

    # Top LGAs by station count
    lga_stats = df.groupby('LGANAME').agg({
        'Station_name': 'count',
        'Number_of_plugs': 'sum'
    }).sort_values('Number_of_plugs', ascending=False)

    lga_stats.columns = ['stations', 'total_plugs']
    lga_stats = lga_stats.head(10).reset_index()

    print(f"    ✓ Top 10 LGAs by total plugs:")
    for idx, row in lga_stats.iterrows():
        print(f"      {row['LGANAME']:40s}: {row['stations']:3d} stations, "
              f"{int(row['total_plugs']):4d} plugs")

    return lga_stats


def merge_reports(validation, chargers, operators, geography):
    """Task 4: Merge all analyses into summary."""
    print("  [4. merge_reports] Merging analysis reports...")

    summary = {
        'validation_stats': {
            'total_records': len(validation),
            'complete_records': validation['is_complete'].sum(),
            'upcoming_stations': validation['is_upcoming'].sum(),
        },
        'top_charger_types': chargers.to_dict('records')[:3],
        'top_operators': operators.to_dict('records')[:3],
        'top_lgas': geography.to_dict('records')[:3],
    }

    # Create summary DataFrame
    summary_df = pd.DataFrame({
        'metric': list(summary['validation_stats'].keys()),
        'value': list(summary['validation_stats'].values())
    })

    print(f"    ✓ Merged {len(chargers)} charger types")
    print(f"    ✓ Merged {len(operators)} operator records")
    print(f"    ✓ Merged {len(geography)} geographic regions")

    return summary_df


# ============================================================================
# Pipeline Execution
# ============================================================================

def run_nsw_ev_pipeline():
    """Build and execute the NSW EV charging pipeline."""

    print("\n" + "=" * 80)
    print("NSW EV CHARGING DATA PIPELINE")
    print("=" * 80)

    # Create tasks
    print("\nBuilding pipeline tasks...")
    task_load = Task('load_raw_data', load_raw_data)

    task_clean = Task(
        'clean_data',
        clean_data,
        dependencies=['load_raw_data']
    )

    task_validate = Task(
        'validate_data',
        validate_data,
        dependencies=['clean_data']
    )

    task_charger = Task(
        'charger_analysis',
        charger_analysis,
        dependencies=['clean_data']
    )

    task_operator = Task(
        'operator_summary',
        operator_summary,
        dependencies=['clean_data']
    )

    task_geography = Task(
        'geographic_analysis',
        geographic_analysis,
        dependencies=['clean_data']
    )

    task_merge = Task(
        'merge_reports',
        merge_reports,
        dependencies=[
            'validate_data',
            'charger_analysis',
            'operator_summary',
            'geographic_analysis'
        ]
    )

    # Create job and validate
    print("Validating DAG structure...")
    job = Job([
        task_load,
        task_clean,
        task_validate,
        task_charger,
        task_operator,
        task_geography,
        task_merge
    ])
    print("✓ DAG validated (no cycles, all dependencies exist)")

    # Execute pipeline
    print("\n" + "=" * 80)
    print("EXECUTING PIPELINE")
    print("=" * 80 + "\n")

    runtime = JobRuntimeLocal(job)

    def on_leaf_complete(task_name, result):
        print(f"\n✓ Pipeline completed: {task_name}")
        print(f"  Shape: {result.shape}")

    results = runtime.run(on_leaf_complete=on_leaf_complete)

    # Print results
    print("\n" + "=" * 80)
    print("PIPELINE RESULTS")
    print("=" * 80)

    print("\nExecution order:")
    for i, task_name in enumerate(runtime.get_execution_order(), 1):
        print(f"  {i}. {task_name}")

    print("\nLeaf tasks (final outputs):")
    for task_name in runtime.get_leaf_tasks():
        print(f"  • {task_name}")

    print("\nFinal report:")
    print(results['merge_reports'].to_string(index=False))

    print("\nValidation details:")
    print(results['validate_data'][['is_complete', 'is_upcoming']].value_counts())

    print("\n" + "=" * 80)
    print("Pipeline execution completed successfully!")
    print("=" * 80)

    return results


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    results = run_nsw_ev_pipeline()
