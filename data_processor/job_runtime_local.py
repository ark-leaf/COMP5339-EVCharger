from typing import Optional, Callable, Dict, Set, List
from collections import deque, defaultdict

import pandas as pd

from data_processor.job import Job


class JobRuntimeLocal:
    """
    Local DAG execution engine that runs tasks sequentially in dependency order.
    Uses topological sort to determine execution order, ensuring dependencies
    are satisfied before each task runs.
    """

    def __init__(self, job: Job):
        self.job = job
        self.results: Dict[str, pd.DataFrame] = {}
        self.execution_order: List[str] = []
        self.leaf_tasks: Set[str] = set()

    def _compute_topological_sort(self) -> List[str]:
        """
        Compute topological sort of task DAG using Kahn's algorithm.
        Returns list of task names in execution order.

        Raises:
            ValueError: If a cycle is detected in the DAG
        """
        # Build in-degree map: how many dependencies each task has
        in_degree = {name: len(task.dependencies) for name, task in self.job.tasks.items()}

        # Build adjacency list: which tasks depend on each task
        dependents = defaultdict(list)
        for name, task in self.job.tasks.items():
            for dep in task.dependencies:
                dependents[dep].append(name)

        # Initialize queue with tasks that have no dependencies
        queue = deque([name for name in self.job.tasks if in_degree[name] == 0])

        # Result: execution order
        execution_order = []

        while queue:
            # Process task with no remaining dependencies
            current = queue.popleft()
            execution_order.append(current)

            # For each task that depends on current task
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                # When all dependencies of dependent are satisfied, add to queue
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Check for cycles: if we didn't process all tasks, there's a cycle
        if len(execution_order) != len(self.job.tasks):
            processed = set(execution_order)
            unprocessed = set(self.job.tasks.keys()) - processed
            raise ValueError(
                f"Cycle detected in DAG. Unprocessed tasks (with cycles): {unprocessed}"
            )

        return execution_order

    def _identify_leaf_tasks(self) -> Set[str]:
        """
        Identify leaf tasks (tasks that nothing depends on).
        These are tasks whose outputs are final results.
        """
        tasks_with_dependents = set()
        for task in self.job.tasks.values():
            tasks_with_dependents.update(task.dependencies)

        leaf_tasks = set(self.job.tasks.keys()) - {
            name for name, task in self.job.tasks.items()
            if any(task.name in self.job.tasks[other].dependencies
                   for other in self.job.tasks if other != name)
        }

        # Simpler: leaf tasks are those that no other task depends on
        all_dependencies = set()
        for task in self.job.tasks.values():
            all_dependencies.update(task.dependencies)

        leaf_tasks = set(self.job.tasks.keys()) - all_dependencies

        return leaf_tasks

    def run(
        self,
        on_leaf_complete: Optional[Callable[[str, pd.DataFrame], None]] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Execute the DAG in topological order.

        Args:
            on_leaf_complete: Optional callback function called when a leaf task
                            completes. Receives (task_name, result_dataframe)

        Returns:
            Dictionary mapping task names to their output DataFrames

        Raises:
            ValueError: If DAG has cycles or task execution fails
            RuntimeError: If a task doesn't return a pandas DataFrame
        """
        # Compute execution order
        self.execution_order = self._compute_topological_sort()
        self.leaf_tasks = self._identify_leaf_tasks()

        self.results = {}

        # Execute tasks in order
        for task_name in self.execution_order:
            task = self.job.tasks[task_name]

            # Collect arguments from upstream task results
            task_args = []
            for dep in task.dependencies:
                if dep not in self.results:
                    raise RuntimeError(
                        f"Dependency '{dep}' for task '{task_name}' not executed yet. "
                        f"This should not happen with correct topological sort."
                    )
                task_args.append(self.results[dep])

            # Execute task function with dependency outputs as arguments
            try:
                result = task.func(*task_args)
            except Exception as e:
                raise RuntimeError(
                    f"Task '{task_name}' failed with error: {type(e).__name__}: {e}"
                ) from e

            # Validate result is a DataFrame
            if not isinstance(result, pd.DataFrame):
                raise RuntimeError(
                    f"Task '{task_name}' returned {type(result).__name__}, "
                    f"expected pandas.DataFrame"
                )

            # Store result
            self.results[task_name] = result

            # Call callback for leaf tasks
            if on_leaf_complete is not None and task_name in self.leaf_tasks:
                on_leaf_complete(task_name, result)

        return self.results

    def get_task_result(self, task_name: str) -> pd.DataFrame:
        """
        Retrieve the result of a specific task.

        Args:
            task_name: Name of the task

        Returns:
            DataFrame output of the task

        Raises:
            KeyError: If task doesn't exist
            RuntimeError: If task hasn't been executed yet
        """
        if task_name not in self.job.tasks:
            raise KeyError(f"Task '{task_name}' not found in job")

        if task_name not in self.results:
            raise RuntimeError(f"Task '{task_name}' has not been executed yet")

        return self.results[task_name]

    def get_execution_order(self) -> List[str]:
        """Get the order in which tasks were (or will be) executed."""
        return self.execution_order

    def get_leaf_tasks(self) -> Set[str]:
        """Get the set of leaf tasks (final outputs)."""
        return self.leaf_tasks
