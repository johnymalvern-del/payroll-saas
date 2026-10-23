"""Job-runner abstraction.

Every long-running operation (payroll run, bulk import, report generation,
reminders, escalation jobs) goes through the `JobRunner` interface.

Two implementations:

  * InProcessRunner - development default, runs jobs in threads inside the
                      API process. No Redis, no separate worker, no extra
                      memory. Loses in-flight jobs when the API restarts.
  * RQRunner        - production. Enqueues jobs onto Redis; a separate RQ
                      worker process executes them. Survives API restarts,
                      supports retries and scheduling.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class JobStatus:
    """Snapshot of a job's state, returned by JobRunner.status()."""

    job_id: str
    state: str  # "queued" | "running" | "finished" | "failed" | "unknown"
    result: Any | None = None
    error: str | None = None


JobCallable = Callable[..., Any]


class JobRunner(ABC):
    """Interface every job-runner backend must implement."""

    @abstractmethod
    def enqueue(self, func: JobCallable, *args: Any, **kwargs: Any) -> str:
        """Schedule `func(*args, **kwargs)` and return a job id."""

    @abstractmethod
    def status(self, job_id: str) -> JobStatus:
        """Return the current state of a job id."""