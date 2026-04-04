from enum import Enum


class TaskName(str, Enum):
    CASCADING_TIMEOUT = "cascading-timeout"
    BYZANTINE_QUEUE_FAULT = "byzantine-queue-fault"
    DISTRIBUTED_LOCK_STARVATION = "distributed-lock-starvation"
    BACKPRESSURE_CASCADE = "backpressure-cascade"
    ROUTE_PARTITION = "route-partition"
    REGISTRY_CORRUPTION = "registry-corruption"
    JOB_GENERATOR_RUNAWAY = "job-generator-runaway"

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

NO_COMMAND_PROVIDED_SENTINEL = "__NO_COMMAND_PROVIDED__"

TASK_MAX_STEPS = {
    TaskName.CASCADING_TIMEOUT: 15,
    TaskName.BYZANTINE_QUEUE_FAULT: 18,
    TaskName.DISTRIBUTED_LOCK_STARVATION: 20,
    TaskName.BACKPRESSURE_CASCADE: 20,
    TaskName.ROUTE_PARTITION: 20,
    TaskName.REGISTRY_CORRUPTION: 18,
    TaskName.JOB_GENERATOR_RUNAWAY: 20,
}

DEFAULT_CONFIGS = {
    "auth": {"delay_ms": 200},
    "gateway": {"auth_timeout_ms": 500},
    "worker": {"db_pool_size": 10, "db_write_delay_ms": 0},
    "job_generator": {"interval_ms": 333},
    "blocked_routes": {"blocked": []},
}
