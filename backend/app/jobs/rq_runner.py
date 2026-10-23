"""RQRunner — production backend.

Enqueues jobs onto Redis. A separate RQ worker process consumes the queue.
Survives API restarts, supports retries and scheduling.

The API process does NOT run jobs itself; it only enqueues and reads status.
This is the split the brief requires: "Redis with a job queue (RQ or Celery)".
"""
from __future__ import annotations

from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

from app.jobs.base import JobCallable, JobRunner, JobStatus


class RQRunner(JobRunner):
    def __init__(self, redis_url: str, queue_name: str = "payroll") -> None:
        self._redis = Redis.from_url(redis_url)
        self._queue = Queue(name=queue_name, connection=self._redis)

    def enqueue(self, func: JobCallable, *args: Any, **kwargs: Any) -> str:
        job = self._queue.enqueue(func, *args, **kwargs)
        return job.id

    def status(self, job_id: str) -> JobStatus:
        try:
            job = Job.fetch(job_id, connection=self._redis)
        except Exception:  # noqa: BLE001 - any fetch failure means "no such job"
            return JobStatus(job_id=job_id, state="unknown", error="no such job")

        state = job.get_status(refresh=True)
        # RQ statuses: queued, started, deferred, finished, stopped, scheduled, failed, canceled
        if state in ("queued", "deferred", "scheduled"):
            return JobStatus(job_id=job_id, state="queued")
        if state in ("started",):
            return JobStatus(job_id=job_id, state="running")
        if state in ("finished",):
            return JobStatus(job_id=job_id, state="finished", result=job.result)
        return JobStatus(
            job_id=job_id, state="failed", error=str(job.exc_info or "unknown failure")
        )
