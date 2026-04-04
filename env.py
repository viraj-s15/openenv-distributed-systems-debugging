import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from constants import DEFAULT_CONFIGS, TASK_MAX_STEPS, TaskName
from fault_injector import inject_fault
from graders import grade_task
from metrics_poller import MetricsPoller
from models import Action, Observation, StepResult
from process_manager import ProcessManager


class DistributedDebugEnv:
    """OpenEnv-compatible distributed systems debugging environment."""

    def __init__(
        self, project_root: Path | None = None, mesh_root: Path | None = None
    ) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parent).resolve()
        self.mesh_root = (
            mesh_root or Path(os.getenv("MESH_ROOT", self.project_root / "mesh"))
        ).resolve()

        self._process_manager = ProcessManager(
            project_root=self.project_root, mesh_root=self.mesh_root
        )
        self._metrics_poller = MetricsPoller(poll_interval_s=2.0)

        self.current_task: TaskName | None = None
        self.max_steps: int = 0
        self.step_count: int = 0
        self.last_exit_code: int = 0
        self.prev_observation: Observation | None = None
        self._baselines: dict[str, int] = {
            "baseline_worker_restart_count": 0,
            "baseline_consumer_stall_count": 0,
        }

    def start(self) -> None:
        if not self._metrics_poller.is_alive():
            self._metrics_poller.start()

    def close(self) -> None:
        self._metrics_poller.stop()

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _restore_defaults(self) -> None:
        self._write_json(
            self.mesh_root / "registry.json",
            {
                "services": {
                    "auth": {"host": "localhost", "port": 3001, "protocol": "http"},
                    "redis": {"host": "localhost", "port": 6379, "protocol": "tcp"},
                    "worker": {
                        "host": "localhost",
                        "port": None,
                        "protocol": "internal",
                    },
                }
            },
        )
        self._write_json(
            self.mesh_root / "auth" / "config.json", DEFAULT_CONFIGS["auth"]
        )
        self._write_json(
            self.mesh_root / "gateway" / "config.json", DEFAULT_CONFIGS["gateway"]
        )
        self._write_json(
            self.mesh_root / "gateway" / "blocked_routes.json",
            DEFAULT_CONFIGS["blocked_routes"],
        )
        self._write_json(
            self.mesh_root / "worker" / "config.json", DEFAULT_CONFIGS["worker"]
        )

    def _truncate_logs(self) -> None:
        for service in ["gateway", "auth", "worker", "job_gen"]:
            Path(f"/tmp/{service}.log").write_text("", encoding="utf-8")

    def _reset_runtime_counters(self) -> None:
        Path("/tmp/worker_restart_count").write_text("0", encoding="utf-8")
        Path("/tmp/consumer_stall_count").write_text("0", encoding="utf-8")

    def _redis_flush(self) -> None:
        subprocess.run(
            ["redis-cli", "FLUSHDB"], check=True, capture_output=True, text=True
        )

    def _read_float(self, value: str, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _is_route_blocked(self) -> bool:
        blocked_file = self.mesh_root / "gateway" / "blocked_routes.json"
        try:
            payload = json.loads(blocked_file.read_text(encoding="utf-8"))
            blocked = payload.get("blocked", [])
            return "gateway->redis" in blocked
        except Exception:
            return False

    def _is_lock_present(self) -> bool:
        result = subprocess.run(
            ["redis-cli", "EXISTS", "LOCK:job_processor"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() == "1"

    def _build_grader_context(self) -> dict[str, Any]:
        return {
            **self._baselines,
            "route_blocked": self._is_route_blocked(),
            "lock_exists": self._is_lock_present(),
        }

    def _blocked_command(self, command: str) -> bool:
        dangerous_patterns = [
            "rm -rf /",
            "kill -9 1",
            "pkill -f uvicorn",
            "> /tmp/gateway.log",
            "> /tmp/auth.log",
            "> /tmp/worker.log",
        ]
        normalized = command.strip().lower()
        return any(pattern in normalized for pattern in dangerous_patterns)

    def _run_command(self, command: str) -> tuple[str, str | None]:
        if self._blocked_command(command):
            self.last_exit_code = 1
            return (
                "BLOCKED: This command would damage the environment infrastructure.",
                "blocked_command",
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                cwd="/",
                env={
                    **os.environ,
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                },
                check=False,
            )
            self.last_exit_code = result.returncode
            output = (result.stdout + result.stderr).strip() or "(no output)"
            return output, None
        except subprocess.TimeoutExpired:
            self.last_exit_code = 124
            return "Command timed out after 10 seconds.", "timeout"
        except Exception as exc:
            self.last_exit_code = 1
            return f"Command execution error: {exc}", str(exc)

    def _compute_reward(
        self,
        command: str,
        current: Observation,
        previous: Observation,
        grader_score: float,
        command_error: str | None,
    ) -> float:
        if grader_score >= 0.95:
            return 1.0

        reward = grader_score * 0.3

        investigation_keywords = [
            "cat",
            "curl",
            "redis-cli",
            "ps",
            "ls",
            "grep",
            "tail",
            "jq",
            "lrange",
            "llen",
            "lrem",
            "kill -hup",
            "keys",
            "ttl",
            "get",
            "del",
            "set",
        ]
        if any(keyword in command.lower() for keyword in investigation_keywords):
            reward += 0.10

        if current.metrics.gateway_success_rate > previous.metrics.gateway_success_rate:
            reward += 0.10

        if current.metrics.queue_depth < previous.metrics.queue_depth:
            reward += 0.10

        if (
            current.metrics.worker_restart_count
            <= previous.metrics.worker_restart_count
        ):
            reward += 0.05

        if (
            current.metrics.consumer_stall_count
            <= previous.metrics.consumer_stall_count
        ):
            reward += 0.05

        if command.strip().lower() in {
            "echo",
            "pwd",
            "whoami",
            "date",
            "true",
            "false",
        }:
            reward -= 0.05

        if (
            self.step_count > 3
            and self.last_exit_code != 0
            and command_error != "blocked_command"
        ):
            reward -= 0.03

        if command_error == "blocked_command":
            reward -= 0.20

        return max(0.0, min(1.0, reward))

    def _status_block(self, metrics: Any) -> str:
        return (
            "=== pipeline status after reset ===\n"
            f"task: {self.current_task.value if self.current_task else 'unknown'}\n"
            "gateway:  running\n"
            "auth:     running\n"
            "worker:   running\n"
            f"queue_depth: {metrics.queue_depth}\n"
            f"gateway_success_rate: {metrics.gateway_success_rate:.2f}"
        )

    def reset(self, task_name: TaskName | str) -> Observation:
        task = TaskName.parse(task_name) if isinstance(task_name, str) else task_name

        self.current_task = task
        self.max_steps = TASK_MAX_STEPS[task]
        self.step_count = 0

        self._truncate_logs()
        self._restore_defaults()
        self._redis_flush()
        self._reset_runtime_counters()

        Path("/tmp/current_task").write_text(task.value, encoding="utf-8")

        self._process_manager.restart_all()
        if not self._process_manager.wait_healthy(timeout_s=30):
            raise RuntimeError("Services failed health checks after reset")

        inject_fault(task, self._process_manager)
        time.sleep(1.0)

        self._metrics_poller.poll_once()
        metrics = self._metrics_poller.get_current_metrics()

        self._baselines = {
            "baseline_worker_restart_count": metrics.worker_restart_count,
            "baseline_consumer_stall_count": metrics.consumer_stall_count,
        }

        observation = Observation(
            command_output=self._status_block(metrics),
            metrics=metrics,
            process_status=self._process_manager.get_status(),
        )
        self.prev_observation = observation
        return observation

    def step(self, action: Action) -> StepResult:
        if not self.current_task:
            raise RuntimeError(
                "Environment not initialized. Call reset(task_name) first."
            )

        self.step_count += 1
        command_output, command_error = self._run_command(action.command)

        self._metrics_poller.poll_once()
        metrics = self._metrics_poller.get_current_metrics()

        observation = Observation(
            command_output=command_output,
            metrics=metrics,
            process_status=self._process_manager.get_status(),
        )

        previous = self.prev_observation or observation
        grader_score = grade_task(
            self.current_task, metrics, self._build_grader_context()
        )
        reward = self._compute_reward(
            action.command, observation, previous, grader_score, command_error
        )
        done = grader_score >= 0.95 or self.step_count >= self.max_steps

        self.prev_observation = observation

        info: dict[str, Any] = {
            "grader_score": round(grader_score, 4),
            "error": command_error,
            "exit_code": self.last_exit_code,
            "task": self.current_task.value if self.current_task else None,
        }

        return StepResult(observation=observation, reward=reward, done=done, info=info)

    def state(self) -> dict[str, Any]:
        self._metrics_poller.poll_once()
        metrics = self._metrics_poller.get_current_metrics()
        return {
            "task": self.current_task.value if self.current_task else None,
            "step_count": self.step_count,
            "max_steps": self.max_steps,
            "metrics": metrics.model_dump(),
            "process_status": self._process_manager.get_status(),
            "baselines": dict(self._baselines),
        }
