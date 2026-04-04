from enum import Enum


class TaskName(str, Enum):
    CASCADING_TIMEOUT = "cascading-timeout"
    BYZANTINE_QUEUE_FAULT = "byzantine-queue-fault"
    DISTRIBUTED_LOCK_STARVATION = "distributed-lock-starvation"
    BACKPRESSURE_CASCADE = "backpressure-cascade"
    ROUTE_PARTITION = "route-partition"

    @classmethod
    def parse(cls, value: str) -> "TaskName":
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"Unknown task: {value}") from exc


ALL_TASKS = [task.value for task in TaskName]

# Baseline default: easy + medium + hard (deadlock/starvation included).
DEFAULT_BASELINE_TASKS = [
    TaskName.CASCADING_TIMEOUT.value,
    TaskName.BYZANTINE_QUEUE_FAULT.value,
    TaskName.DISTRIBUTED_LOCK_STARVATION.value,
]

DEFAULT_BASELINE_TASK_ENUMS = [
    TaskName.CASCADING_TIMEOUT,
    TaskName.BYZANTINE_QUEUE_FAULT,
    TaskName.DISTRIBUTED_LOCK_STARVATION,
]

TASK_MAX_STEPS = {
    TaskName.CASCADING_TIMEOUT: 12,
    TaskName.BYZANTINE_QUEUE_FAULT: 12,
    TaskName.DISTRIBUTED_LOCK_STARVATION: 14,
    TaskName.BACKPRESSURE_CASCADE: 14,
    TaskName.ROUTE_PARTITION: 14,
}

DEFAULT_CONFIGS = {
    "auth": {"delay_ms": 200},
    "gateway": {"auth_timeout_ms": 500},
    "worker": {"db_pool_size": 10, "db_write_delay_ms": 0},
    "blocked_routes": {"blocked": []},
}