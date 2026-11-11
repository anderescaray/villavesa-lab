"""Background optimizer jobs (in-memory; the server is single-process)."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vlab.optimize import Progress

MAX_JOBS = 32


@dataclass
class Job:
    id: str
    kind: str
    progress: Progress = field(default_factory=Progress)
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)

    def view(self) -> dict[str, Any]:
        p = self.progress
        return {
            "job_id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": 1.0 if self.status == "done" else round(p.progress, 3),
            "stage": p.stage if self.status in ("running", "done") else self.status,
            "log": list(p.log),
            "history": list(p.history),
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    """Runs one optimizer job at a time; later jobs wait in the queue."""

    def __init__(self) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Progress], dict[str, Any]]) -> Job:
        job = Job(uuid.uuid4().hex[:12], kind)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > MAX_JOBS:
                self._jobs.popitem(last=False)

        def run() -> None:
            with self._run_lock:
                job.status = "running"
                job.progress.started = time.perf_counter()
                try:
                    job.result = fn(job.progress)
                    job.status = "done"
                except Exception as exc:
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.status = "error"

        threading.Thread(target=run, name=f"vlab-job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)
