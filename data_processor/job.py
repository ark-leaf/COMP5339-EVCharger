from data_processor.task import Task


class Job:
    """
    The DAG blueprint that acts as a container and validator for Tasks in a DAG data processing pipeline.

    Attributes:
        tasks (dict[str, Task]): A dictionary mapping task names to Task objects.
    """
    def __init__(self, tasks: list[Task]):
        self.tasks = {t.name: t for t in tasks}
        self._validate()

    def _validate(self) -> None:
        """Validates the graph to ensure no missing upstream dependencies exist."""
        for name, task in self.tasks.items():
            for dep in task.dependencies:
                if dep not in self.tasks:
                    raise ValueError(f"Dependency '{dep}' for task '{name}' not found.")