import subprocess
import threading
from pathlib import Path

import httpx

from models import SystemMetrics


class MetricsPoller(threading.Thread):
    """Background metrics poller with last-known-good caching."""

    def __init__(self, poll_interval_s: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.poll_interval_s = poll_interval_s
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest: dict[str, float | int] = {
            "gateway_success_rate": 0.0,
            "gateway_p99_latency_ms": 0.0,
            "queue_depth": 0,
            "worker_restart_count": 0,
            "consumer_stall_count": 0,
        }

    def stop(self) -> None:
        self._stop_event.set()

    def _read_counter(self, path: str) -> int:
        file_path = Path(path)
        if not file_path.exists():
            return 0
        try:
            return int(file_path.read_text().strip() or "0")
        except ValueError:
            return 0

    def _poll_gateway(self) -> dict[str, float]:
        with httpx.Client(timeout=1.0) as client:
            response = client.get("http://localhost:3000/health")
            response.raise_for_status()
            payload = response.json()

        success_rate = float(
            payload.get("success_rate", payload.get("gateway_success_rate", 0.0))
        )
        p99 = float(
            payload.get("p99_latency_ms", payload.get("gateway_p99_latency_ms", 0.0))
        )
        return {
            "gateway_success_rate": max(0.0, min(1.0, success_rate)),
            "gateway_p99_latency_ms": max(0.0, p99),
        }

    def _poll_queue_depth(self) -> int:
        result = subprocess.run(
            ["redis-cli", "LLEN", "job_queue"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return int(self._latest["queue_depth"])
        try:
            return max(0, int(result.stdout.strip() or "0"))
        except ValueError:
            return int(self._latest["queue_depth"])

    def poll_once(self) -> None:
        snapshot = dict(self._latest)
        try:
            snapshot.update(self._poll_gateway())
        except Exception:
            pass

        snapshot["queue_depth"] = self._poll_queue_depth()
        snapshot["worker_restart_count"] = self._read_counter(
            "/tmp/worker_restart_count"
        )
        snapshot["consumer_stall_count"] = self._read_counter(
            "/tmp/consumer_stall_count"
        )

        with self._lock:
            self._latest = snapshot

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.poll_interval_s)

    def get_current_metrics(self) -> SystemMetrics:
        with self._lock:
            snapshot = dict(self._latest)
        return SystemMetrics.model_validate(snapshot)
