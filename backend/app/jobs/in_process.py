"""InProcessRunner — development default.

Runs jobs in a thread pool inside the API process. This is a real job runner
in the sense that the caller does not block: `enqueue()` returns immediately
with a job id, the job runs on a background thread, and `status()` reports
progress.

Limits (why this is not the production backend):

  * Jobs are lost if the API process restarts.
  * No retry policy.
  * No scheduling (cron or delayed).
  * Consumes memory from the API process — the API and the jobs compete.

Production uses RQRunner which fixes all four.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.jobs.base import JobCallable, JobRunner, JobStatus


class InProcessRunner(JobRunner):
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="inproc-job"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, JobStatus] = {}

    def _set(self, job_id: str, status: JobStatus) -> None:
        with self._lock:
            self._jobs[job_id] = status

    def _run(self, job_id: str, func: JobCallable, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._set(job_id, JobStatus(job_id=job_id, state="running"))
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - we want to record any failure
            self._set(
                job_id,
                JobStatus(job_id=job_id, state="failed", error=f"{type(exc).__name__}: {exc}"),
            )
            return
        self._set(job_id, JobStatus(job_id=job_id, state="finished", result=result))

    def enqueue(self, func: JobCallable, *args: Any, **kwargs: Any) -> str:
        job_id = uuid.uuid4().hex
        self._set(job_id, JobStatus(job_id=job_id, state="queued"))
        self._executor.submit(self._run, job_id, func, args, kwargs)
        return job_id

    def status(self, job_id: str) -> JobStatus:
        with self._lock:
            return self._jobs.get(
                job_id, JobStatus(job_id=job_id, state="unknown", error="no such job")
            )
