from typing import Callable, Any


class Task:
    """
    A pure structural definition of a node in a DAG data processing job.

    Attributes:
        name (str): The unique identifier for this task in the DAG.
        func (Callable): The Python function to execute. The function's arguments
            must match the order of the specified `dependencies`. All functions
            MUST return a pandas DataFrame.
        dependencies (list[str]): A list of upstream task names that must complete
            before this task can execute. Defaults to an empty list.
    """

    def __init__(self, name: str,
                 func: Callable[..., Any],
                 dependencies: list[str] = None):
        self.name = name
        self.func = func
        self.dependencies = dependencies or []
