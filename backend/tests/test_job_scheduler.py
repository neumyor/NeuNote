from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.kb import create_job, ensure_kb, load_job


class _FakeFuture:
    def done(self) -> bool:
        return False


class _FakeExecutor:
    def __init__(self) -> None:
        self.submitted: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def submit(self, fn: object, *args: object, **kwargs: object) -> _FakeFuture:
        self.submitted.append((fn, args, kwargs))
        return _FakeFuture()


class JobSchedulerTests(unittest.TestCase):
    def test_drain_queue_saves_attempt_without_running_job_inline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            job = create_job(root, "paper-a", "Paper A")
            root_key = str(root.resolve())
            executor = _FakeExecutor()

            try:
                with main._scheduler_lock:
                    main._scheduler_roots[root_key] = {"root": root, "config": {"max_concurrency": 1}}
                with patch.object(main, "_get_executor", return_value=executor):
                    main._drain_enrichment_queue(root)

                saved = load_job(root, job["id"])
                self.assertEqual(saved["attempts"], 1)
                self.assertEqual(len(executor.submitted), 1)
            finally:
                with main._scheduler_lock:
                    main._scheduler_roots.pop(root_key, None)
                    main._running_futures.pop(job["id"], None)
                    main._future_roots.pop(job["id"], None)

    def test_drain_queue_recovers_after_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            job = create_job(root, "paper-a", "Paper A")
            root_key = str(root.resolve())
            executor = _FakeExecutor()

            try:
                with main._scheduler_lock:
                    main._scheduler_roots.pop(root_key, None)
                with patch.object(main, "_get_executor", return_value=executor):
                    main._drain_enrichment_queue(root)

                saved = load_job(root, job["id"])
                self.assertEqual(saved["attempts"], 1)
                self.assertEqual(len(executor.submitted), 1)
            finally:
                with main._scheduler_lock:
                    main._scheduler_roots.pop(root_key, None)
                    main._running_futures.pop(job["id"], None)
                    main._future_roots.pop(job["id"], None)


if __name__ == "__main__":
    unittest.main()
