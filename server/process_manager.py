import os
import signal
import subprocess
import time
from pathlib import Path

import httpx


class ProcessManager:
    """Tracks Bun service processes and lifecycle state."""

    def __init__(
        self, project_root: Path | None = None, mesh_root: Path | None = None
    ) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parent.parent).resolve()
        self.mesh_root = (
            mesh_root or Path(os.getenv("MESH_ROOT", self.project_root / "mesh"))
        ).resolve()

        self._service_scripts = {
            "gateway": self.project_root / "mesh" / "gateway" / "index.ts",
            "auth": self.project_root / "mesh" / "auth" / "index.ts",
            "worker": self.project_root / "mesh" / "worker" / "index.ts",
        }
        self._job_generator_script = (
            self.project_root / "mesh" / "worker" / "job_generator.ts"
        )
        self._health_urls = {
            "gateway": "http://localhost:3000/health",
            "auth": "http://localhost:3001/health",
        }

        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._log_handles: dict[str, object] = {}

    @staticmethod
    def _pid_path(service: str) -> Path:
        return Path(f"/tmp/{service}.pid")

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _read_pid(self, service: str) -> int | None:
        path = self._pid_path(service)
        if not path.exists():
            return None
        try:
            pid = int(path.read_text().strip())
        except (TypeError, ValueError):
            return None
        return pid if self._is_pid_alive(pid) else None

    def _write_pid(self, service: str, pid: int) -> None:
        self._pid_path(service).write_text(str(pid))

    def _spawn_service(self, service: str, script: Path, log_path: Path) -> None:
        log_handle = open(log_path, "a", encoding="utf-8")
        env = {
            **os.environ,
            "MESH_ROOT": str(self.mesh_root),
        }
        process = subprocess.Popen(
            ["bun", "run", str(script)],
            cwd=str(self.project_root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        self._processes[service] = process
        self._log_handles[service] = log_handle
        self._write_pid(service, process.pid)

    def start_all(self) -> None:
        for service, script in self._service_scripts.items():
            existing_pid = self._read_pid(service)
            if existing_pid:
                continue
            self._spawn_service(service, script, Path(f"/tmp/{service}.log"))

        if not self._read_pid("job_generator"):
            self._spawn_service(
                "job_generator", self._job_generator_script, Path("/tmp/job_gen.log")
            )

    def _terminate_pid(self, pid: int, timeout_s: float = 0.5) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not self._is_pid_alive(pid):
                return
            time.sleep(0.05)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def stop_all(self) -> None:
        for service in ["gateway", "auth", "worker", "job_generator"]:
            pid = self._read_pid(service)
            if pid:
                self._terminate_pid(pid)
            pid_path = self._pid_path(service)
            if pid_path.exists():
                pid_path.unlink(missing_ok=True)

        for handle in self._log_handles.values():
            try:
                handle.close()
            except Exception:
                pass

        self._processes.clear()
        self._log_handles.clear()

    def restart_all(self) -> None:
        self.stop_all()
        self.start_all()

    def sighup(self, service: str) -> None:
        pid = self._read_pid(service)
        if not pid:
            raise RuntimeError(f"Service not running: {service}")
        os.kill(pid, signal.SIGHUP)

    def wait_healthy(self, timeout_s: int = 30) -> bool:
        deadline = time.time() + timeout_s
        with httpx.Client(timeout=1.0) as client:
            while time.time() < deadline:
                try:
                    gateway_ok = (
                        client.get(self._health_urls["gateway"]).status_code == 200
                    )
                    auth_ok = client.get(self._health_urls["auth"]).status_code == 200
                    if gateway_ok and auth_ok:
                        return True
                except Exception:
                    pass
                time.sleep(1)
        return False

    def get_status(self) -> dict[str, str]:
        status: dict[str, str] = {}
        for service in ["gateway", "auth", "worker", "job_generator"]:
            pid = self._read_pid(service)
            status[service] = f"running pid={pid}" if pid else "stopped"
        return status

    def get_pid(self, service: str) -> int | None:
        return self._read_pid(service)

    def close(self) -> None:
        self.stop_all()
