import json
import subprocess
from pathlib import Path

from .constants import TaskName
from .process_manager import ProcessManager


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def inject_cascading_timeout(pm: ProcessManager) -> None:
    _write_json(pm.mesh_root / "auth" / "config.json", {"delay_ms": 1500})
    _write_json(pm.mesh_root / "gateway" / "config.json", {"auth_timeout_ms": 500})
    pm.sighup("auth")
    pm.sighup("gateway")


def inject_byzantine_queue_fault(pm: ProcessManager) -> None:
    subprocess.run(
        ["redis-cli", "LPUSH", "job_queue", '{"id":"poison-001","payload":{{BROKEN'],
        check=True,
    )


def inject_distributed_lock_starvation(pm: ProcessManager) -> None:
    subprocess.run(
        ["redis-cli", "SET", "LOCK:job_processor", "dead-worker-pid-9999"], check=True
    )


def inject_backpressure_cascade(pm: ProcessManager) -> None:
    _write_json(
        pm.mesh_root / "worker" / "config.json",
        {"db_pool_size": 1, "db_write_delay_ms": 800},
    )
    pm.sighup("worker")


def inject_route_partition(pm: ProcessManager) -> None:
    _write_json(
        pm.mesh_root / "gateway" / "blocked_routes.json",
        {"blocked": ["gateway->redis"]},
    )
    pm.sighup("gateway")


def inject_registry_corruption(pm: ProcessManager) -> None:
    _write_json(
        pm.mesh_root / "registry.json",
        {
            "services": {
                "auth": {"host": "invalid-auth-host", "port": 3001, "protocol": "http"},
                "redis": {"host": "localhost", "port": 6379, "protocol": "tcp"},
                "worker": {"host": "localhost", "port": None, "protocol": "internal"},
            }
        },
    )
    pm.sighup("gateway")


def inject_job_generator_runaway(pm: ProcessManager) -> None:
    _write_json(
        pm.mesh_root / "worker" / "job_generator_config.json", {"interval_ms": 10}
    )
    pm.sighup("job_generator")


def inject_fault(task_name: TaskName | str, pm: ProcessManager) -> None:
    task = TaskName.parse(task_name) if isinstance(task_name, str) else task_name

    if task is TaskName.CASCADING_TIMEOUT:
        inject_cascading_timeout(pm)
        return
    if task is TaskName.BYZANTINE_QUEUE_FAULT:
        inject_byzantine_queue_fault(pm)
        return
    if task is TaskName.DISTRIBUTED_LOCK_STARVATION:
        inject_distributed_lock_starvation(pm)
        return
    if task is TaskName.BACKPRESSURE_CASCADE:
        inject_backpressure_cascade(pm)
        return
    if task is TaskName.ROUTE_PARTITION:
        inject_route_partition(pm)
        return
    if task is TaskName.REGISTRY_CORRUPTION:
        inject_registry_corruption(pm)
        return
    if task is TaskName.JOB_GENERATOR_RUNAWAY:
        inject_job_generator_runaway(pm)
        return
    raise ValueError(f"Unknown task: {task_name}")
