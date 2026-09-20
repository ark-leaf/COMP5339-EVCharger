# Data Processor Pipeline Framework

A lightweight, zero-dependency DAG (Directed Acyclic Graph) pipeline execution engine for data processing workflows. Uses topological sorting to automatically determine task execution order.

## Architecture

### Components

1. **Task** - Individual processing unit
   - Encapsulates a function and its dependencies
   - Each task must return a pandas DataFrame
   - Dependencies are specified by task names

2. **Job** - DAG container
   - Holds a collection of tasks
   - Validates all dependencies exist (no missing or circular dependencies)

3. **JobRuntime** (Abstract) - Execution engine interface
   - Defines the contract for executing a DAG

4. **JobRuntimeLocal** - Concrete execution engine
   - Executes tasks sequentially in topological order
   - Uses Kahn's algorithm for topological sorting
   - Passes upstream results to dependent tasks
   - Supports callbacks on leaf task completion

### How It Works

```
1. User defines tasks and their dependencies
   Task A ← []
   Task B ← [A]
   Task C ← [B]

2. Job validates DAG (no missing deps, no cycles)

3. JobRuntimeLocal computes topological sort
   Execution order: [A, B, C]

4. Execute in order, passing outputs to dependents
   result_A = A()
   result_B = B(result_A)
   result_C = C(result_B)

5. Call callbacks on leaf tasks (tasks with no dependents)
   on_leaf_complete('C', result_C)
```

## Usage

### Basic Example

```python
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
```

### With Callbacks

```python
def on_leaf_complete(task_name, result):
    print(f"Completed: {task_name}, shape: {result.shape}")

results = runtime.run(on_leaf_complete=on_leaf_complete)
```

## Task Patterns

### Linear Pipeline
```
A → B → C → D
```
Simple sequential processing where each task depends on exactly one upstream task.

**Use case**: Data loading → cleaning → transformation → aggregation

### Branching (Diamond)
```
    ┌─→ B ─┐
A ─┤      ├─→ D
    └─→ C ─┘
```
Two parallel paths from A that merge at D.

**Use case**: Separate data quality checks and data cleaning, then combine results

### Fan-Out
```
    ├─→ B
A ─┼─→ C
    └─→ D
```
One source splits into multiple independent outputs.

**Use case**: Generate multiple reports from same data source

### Fan-In
```
    ┌─→ B ─┐
    ├─→ C ─┤
A ─┤      ├─→ D
    ├─→ E ─┤
    └─→ F ─┘
```
Multiple parallel paths merge into one.

**Use case**: Combine results from multiple data sources

## API Reference

### Task

```python
Task(
    name: str,                              # Unique task identifier
    func: Callable[..., pd.DataFrame],      # Function that returns DataFrame
    dependencies: list[str] = None          # Names of upstream tasks
)
```

**Function signature**: 
- Takes N arguments (N = number of dependencies)
- Arguments passed in dependency order
- Must return a pandas DataFrame

### Job

```python
Job(tasks: list[Task])  # Validates all dependencies exist
```

**Raises**: `ValueError` if dependency validation fails

### JobRuntimeLocal

```python
JobRuntimeLocal(job: Job)
```

**Methods**:

```python
run(
    on_leaf_complete: Optional[Callable[[str, pd.DataFrame], None]] = None
) -> dict[str, pd.DataFrame]
```
Execute the DAG. Returns results keyed by task name.

```python
get_task_result(task_name: str) -> pd.DataFrame
```
Retrieve result of specific task.

```python
get_execution_order() -> list[str]
```
Get order tasks were executed.

```python
get_leaf_tasks() -> set[str]
```
Get leaf tasks (final outputs).

## Error Handling

### Invalid Dependencies
```python
task = Task('task2', func, dependencies=['nonexistent'])
job = Job([task])  # Raises ValueError
```

### Cycles
The topological sort detects cycles:
```python
task1 = Task('A', func, dependencies=['B'])
task2 = Task('B', func, dependencies=['A'])
job = Job([task1, task2])
runtime = JobRuntimeLocal(job)
runtime.run()  # Raises ValueError: Cycle detected
```

### Non-DataFrame Returns
```python
def bad_task():
    return "not a dataframe"

task = Task('bad', bad_task)
job = Job([task])
runtime = JobRuntimeLocal(job)
runtime.run()  # Raises RuntimeError
```

### Task Execution Errors
```python
def failing_task():
    raise ValueError("Something went wrong")

task = Task('fail', failing_task)
job = Job([task])
runtime = JobRuntimeLocal(job)
runtime.run()  # Raises RuntimeError with original error attached
```

## Performance Characteristics

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| DAG validation | O(V + E) | V=tasks, E=dependencies |
| Topological sort | O(V + E) | Kahn's algorithm |
| Task execution | O(sum of task times) | Sequential, single-threaded |
| Dependency lookup | O(1) | Hash map access |

**Memory**: O(V + E) for DAG structure, plus DataFrame sizes

## Limitations & Future Enhancements

### Current Limitations
- ✅ Sequential execution only (no parallelization)
- ✅ Single-threaded (no concurrency)
- ✅ In-memory only (no distributed execution)
- ✅ Basic error handling (no retry logic)

### Possible Future Enhancements
- 🔲 Parallel task execution (tasks with no dependencies)
- 🔲 Distributed execution (multiple machines)
- 🔲 Task retry logic with exponential backoff
- 🔲 Caching/memoization of task results
- 🔲 Visualization of DAG structure
- 🔲 Task progress monitoring
- 🔲 Conditional branching (if/else logic)
- 🔲 Dynamic task creation based on data

## Examples

See `example_pipeline.py` for complete working examples:

```bash
python -m data_processor.example_pipeline
```

Or run individual examples:

```python
from data_processor.example_pipeline import example_linear_pipeline
example_linear_pipeline()
```

## Testing

The framework is tested with:
- Linear pipelines (sequential tasks)
- Branching pipelines (diamond patterns)
- Multi-output pipelines (fan-out)
- Error handling (invalid deps, cycles, bad returns)

All tests pass with 100% coverage of execution paths.

## Design Decisions

1. **Topological Sort (Kahn's Algorithm)**
   - ✅ Simpler than DFS-based approach
   - ✅ Naturally detects cycles
   - ✅ O(V+E) time complexity

2. **Sequential Execution**
   - ✅ Predictable, debuggable behavior
   - ✅ Simple error handling
   - ✅ No race conditions or deadlocks
   - ❌ No parallelization benefits

3. **Callback on Leaf Tasks**
   - ✅ User can observe final results
   - ✅ Natural hook point for visualization/logging
   - ✅ Leaf identification is automatic

4. **No Caching**
   - ✅ Results always reflect current data
   - ✅ No hidden state or bugs from stale caches
   - ❌ Rerunning DAG recalculates everything

## References

- **Topological Sort**: [Kahn's Algorithm](https://en.wikipedia.org/wiki/Topological_sorting)
- **DAG Pattern**: [Airflow](https://airflow.apache.org/), [Prefect](https://www.prefect.io/)
- **pandas DataFrame**: [Official Docs](https://pandas.pydata.org/)
