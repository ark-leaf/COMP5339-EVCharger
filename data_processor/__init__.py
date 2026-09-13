"""
Data processing pipeline framework using Directed Acyclic Graph (DAG) pattern.

This module provides:
- Task: Individual processing units in a DAG
- Job: DAG container with validation
- JobRuntime: Abstract base class for execution engines
- JobRuntimeLocal: Concrete local execution engine (topological sort + sequential execution)

Example usage:
    from data_processor.task import Task
    from data_processor.job import Job
    from data_processor.job_runtime_local import JobRuntimeLocal
    import pandas as pd

    # Define tasks
    def load_data():
        return pd.DataFrame({'a': [1, 2, 3]})

    def transform_data(df):
        df['b'] = df['a'] * 2
        return df

    def aggregate_data(df):
        return df.groupby('b').sum()

    # Create tasks
    task1 = Task('load', load_data)
    task2 = Task('transform', transform_data, dependencies=['load'])
    task3 = Task('aggregate', aggregate_data, dependencies=['transform'])

    # Create and run job
    job = Job([task1, task2, task3])
    runtime = JobRuntimeLocal(job)
    results = runtime.run()

    print(results['aggregate'])
"""

from data_processor.task import Task
from data_processor.job import Job
from data_processor.job_runtime import JobRuntime
from data_processor.job_runtime_local import JobRuntimeLocal

__all__ = ['Task', 'Job', 'JobRuntime', 'JobRuntimeLocal']
