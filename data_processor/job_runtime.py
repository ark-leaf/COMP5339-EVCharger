from abc import ABC, abstractmethod
from typing import Optional, Callable

import pandas as pd

from data_processor.job import Job


class JobRuntime(ABC):
    """
    Abstract base class defining the strict contract for all DAG execution engines.
    """
    def __init__(self, job: Job):
        self.job = job

    @abstractmethod
    def run(self, on_leaf_complete: Optional[Callable[[str, pd.DataFrame], None]] = None) -> dict[str, pd.DataFrame]:
        pass
