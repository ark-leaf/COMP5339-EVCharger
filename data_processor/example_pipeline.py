"""
Example DAG pipeline demonstrating the data processing framework.

This example shows:
1. How to define tasks with dependencies
2. How tasks can take multiple upstream inputs
3. How to run the DAG with topological ordering
4. How to track execution and handle callbacks
"""

import pandas as pd
from data_processor.task import Task
from data_processor.job import Job
from data_processor.job_runtime_local import JobRuntimeLocal


# ============================================================================
# Example 1: Simple Linear Pipeline (A → B → C)
# ============================================================================

def example_linear_pipeline():
    """
    Simple linear pipeline: load data → clean → aggregate
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Linear Pipeline (A → B → C)")
    print("=" * 70)

    # Task 1: Load sample data
    def load_data():
        print("  [Task: load_data] Loading sample data...")
        df = pd.DataFrame({
            'city': ['Sydney', 'Melbourne', 'Brisbane', 'Sydney', 'Melbourne'],
            'year': [2020, 2020, 2020, 2021, 2021],
            'ev_count': [100, 80, 50, 150, 120]
        })
        print(f"    → Loaded {len(df)} rows")
        return df

    # Task 2: Clean and transform
    def clean_data(df):
        print("  [Task: clean_data] Cleaning data...")
        df = df.dropna()
        df['ev_count'] = df['ev_count'].astype(int)
        print(f"    → Cleaned {len(df)} rows")
        return df

    # Task 3: Aggregate by year
    def aggregate_by_year(df):
        print("  [Task: aggregate_by_year] Aggregating by year...")
        result = df.groupby('year')['ev_count'].sum().reset_index()
        print(f"    → Aggregated to {len(result)} groups")
        return result

    # Create tasks
    task_load = Task('load_data', load_data)
    task_clean = Task('clean_data', clean_data, dependencies=['load_data'])
    task_agg = Task('aggregate_by_year', aggregate_by_year, dependencies=['clean_data'])

    # Create and run job
    job = Job([task_load, task_clean, task_agg])
    runtime = JobRuntimeLocal(job)

    def on_leaf_complete(task_name, result):
        print(f"  ✓ Leaf task '{task_name}' completed\n")
        print(f"Final result:\n{result}")

    results = runtime.run(on_leaf_complete=on_leaf_complete)
    print(f"\nExecution order: {runtime.get_execution_order()}")
    print(f"Leaf tasks: {runtime.get_leaf_tasks()}")


# ============================================================================
# Example 2: Branching Pipeline (Diamond shape: A → B,C → D)
# ============================================================================

def example_branching_pipeline():
    """
    Branching pipeline: load → [clean & validate] → merge results
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Branching Pipeline (Diamond: A → B,C → D)")
    print("=" * 70)

    # Task 1: Load data
    def load_data():
        print("  [Task: load_data] Loading data...")
        df = pd.DataFrame({
            'id': [1, 2, 3],
            'value': [10, 20, 30],
            'status': ['active', 'active', 'inactive']
        })
        print(f"    → Loaded {len(df)} rows")
        return df

    # Task 2: Data quality checks
    def validate_data(df):
        print("  [Task: validate_data] Validating data...")
        # Mark rows as valid/invalid
        df['is_valid'] = df['status'] == 'active'
        print(f"    → {df['is_valid'].sum()} valid rows")
        return df

    # Task 3: Data cleaning
    def clean_data(df):
        print("  [Task: clean_data] Cleaning data...")
        df = df.copy()
        df['value'] = df['value'] * 1.1  # Apply 10% adjustment
        print(f"    → Cleaned values")
        return df

    # Task 4: Merge results (takes both cleaned and validated data)
    def merge_results(validated, cleaned):
        print("  [Task: merge_results] Merging validated and cleaned data...")
        result = pd.DataFrame({
            'id': validated['id'],
            'adjusted_value': cleaned['value'],
            'is_valid': validated['is_valid']
        })
        print(f"    → Merged result has {len(result)} rows")
        return result

    # Create tasks
    task_load = Task('load_data', load_data)
    task_validate = Task('validate_data', validate_data, dependencies=['load_data'])
    task_clean = Task('clean_data', clean_data, dependencies=['load_data'])
    task_merge = Task(
        'merge_results',
        merge_results,
        dependencies=['validate_data', 'clean_data']
    )

    # Create and run job
    job = Job([task_load, task_validate, task_clean, task_merge])
    runtime = JobRuntimeLocal(job)

    def on_leaf_complete(task_name, result):
        print(f"  ✓ Leaf task '{task_name}' completed\n")
        print(f"Final result:\n{result}")

    results = runtime.run(on_leaf_complete=on_leaf_complete)
    print(f"\nExecution order: {runtime.get_execution_order()}")
    print(f"Leaf tasks: {runtime.get_leaf_tasks()}")


# ============================================================================
# Example 3: Multi-Output Pipeline (A → B,C,D)
# ============================================================================

def example_multi_output_pipeline():
    """
    Multi-output pipeline: load → [three parallel outputs]
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Multi-Output Pipeline (A → B,C,D in parallel)")
    print("=" * 70)

    # Task 1: Load data
    def load_data():
        print("  [Task: load_data] Loading EV charging data...")
        df = pd.DataFrame({
            'station': ['A', 'B', 'C', 'D'],
            'chargers': [4, 2, 6, 3],
            'type': ['DC', 'AC', 'DC', 'AC']
        })
        print(f"    → Loaded {len(df)} stations")
        return df

    # Task 2: Count by type
    def count_by_type(df):
        print("  [Task: count_by_type] Counting chargers by type...")
        result = df.groupby('type')['chargers'].sum().reset_index()
        print(f"    → {len(result)} charger types")
        return result

    # Task 3: Get high-capacity stations
    def filter_high_capacity(df):
        print("  [Task: filter_high_capacity] Filtering high-capacity...")
        result = df[df['chargers'] >= 4]
        print(f"    → Found {len(result)} high-capacity stations")
        return result

    # Task 4: Statistics
    def compute_stats(df):
        print("  [Task: compute_stats] Computing statistics...")
        result = pd.DataFrame({
            'metric': ['total_chargers', 'avg_chargers', 'max_chargers'],
            'value': [
                df['chargers'].sum(),
                df['chargers'].mean(),
                df['chargers'].max()
            ]
        })
        print(f"    → Computed {len(result)} statistics")
        return result

    # Create tasks
    task_load = Task('load_data', load_data)
    task_by_type = Task('count_by_type', count_by_type, dependencies=['load_data'])
    task_high_cap = Task(
        'filter_high_capacity',
        filter_high_capacity,
        dependencies=['load_data']
    )
    task_stats = Task('compute_stats', compute_stats, dependencies=['load_data'])

    # Create and run job
    job = Job([task_load, task_by_type, task_high_cap, task_stats])
    runtime = JobRuntimeLocal(job)

    def on_leaf_complete(task_name, result):
        print(f"  ✓ Leaf task '{task_name}' completed")
        print(f"    Result shape: {result.shape}")

    results = runtime.run(on_leaf_complete=on_leaf_complete)
    print(f"\nExecution order: {runtime.get_execution_order()}")
    print(f"Leaf tasks (multiple outputs): {runtime.get_leaf_tasks()}")
    print("\nAll results:")
    for task_name in runtime.get_leaf_tasks():
        print(f"\n{task_name}:\n{results[task_name]}")


# ============================================================================
# Example 4: Error Handling
# ============================================================================

def example_error_handling():
    """
    Demonstrate error handling with invalid dependencies and cycles
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Error Handling")
    print("=" * 70)

    def dummy_task():
        return pd.DataFrame({'a': [1]})

    # Test 1: Invalid dependency reference
    print("\n[Test 1] Invalid dependency reference:")
    try:
        task1 = Task('task1', dummy_task)
        task2 = Task('task2', dummy_task, dependencies=['nonexistent'])
        job = Job([task1, task2])
        print("  ✗ Should have failed!")
    except ValueError as e:
        print(f"  ✓ Caught error: {e}")

    # Test 2: Invalid return type
    print("\n[Test 2] Task returns non-DataFrame:")
    def bad_task():
        return "not a dataframe"

    try:
        task = Task('bad', bad_task)
        job = Job([task])
        runtime = JobRuntimeLocal(job)
        results = runtime.run()
        print("  ✗ Should have failed!")
    except RuntimeError as e:
        print(f"  ✓ Caught error: {type(e).__name__}")


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("DATA PROCESSOR PIPELINE FRAMEWORK EXAMPLES")
    print("=" * 70)

    example_linear_pipeline()
    example_branching_pipeline()
    example_multi_output_pipeline()
    example_error_handling()

    print("\n" + "=" * 70)
    print("All examples completed successfully!")
    print("=" * 70)
