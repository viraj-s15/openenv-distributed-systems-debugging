from graders import (
    grade_backpressure_cascade,
    grade_byzantine_queue_fault,
    grade_cascading_timeout,
    grade_distributed_lock_starvation,
    grade_route_partition,
)
from models import SystemMetrics


def _metrics(
    *,
    success_rate: float = 0.0,
    p99: float = 1000.0,
    depth: int = 10,
    restarts: int = 0,
    stalls: int = 0,
) -> SystemMetrics:
    return SystemMetrics(
        gateway_success_rate=success_rate,
        gateway_p99_latency_ms=p99,
        queue_depth=depth,
        worker_restart_count=restarts,
        consumer_stall_count=stalls,
    )


def test_grade_cascading_timeout_boundaries() -> None:
    assert grade_cascading_timeout(_metrics(success_rate=1.0), {}) == 1.0
    assert grade_cascading_timeout(_metrics(success_rate=0.5), {}) == 0.3


def test_grade_byzantine_queue_fault_cases() -> None:
    ctx = {"baseline_worker_restart_count": 3}
    assert grade_byzantine_queue_fault(_metrics(depth=0, restarts=3), ctx) == 1.0
    assert grade_byzantine_queue_fault(_metrics(depth=0, restarts=8), ctx) == 0.6
    assert grade_byzantine_queue_fault(_metrics(depth=40, restarts=10), ctx) == 0.0


def test_grade_distributed_lock_starvation_cases() -> None:
    ctx_locked = {"baseline_consumer_stall_count": 0, "lock_exists": True}
    ctx_unlocked = {"baseline_consumer_stall_count": 0, "lock_exists": False}

    assert grade_distributed_lock_starvation(_metrics(depth=2, stalls=0), ctx_unlocked) == 1.0
    assert grade_distributed_lock_starvation(_metrics(depth=10, stalls=0), ctx_unlocked) == 0.6
    assert grade_distributed_lock_starvation(_metrics(depth=10, stalls=3), ctx_locked) == 0.0


def test_grade_backpressure_cascade_continuous() -> None:
    assert grade_backpressure_cascade(_metrics(depth=0), {}) == 1.0
    assert grade_backpressure_cascade(_metrics(depth=100), {}) == 0.5
    assert grade_backpressure_cascade(_metrics(depth=200), {}) == 0.0


def test_grade_route_partition_threshold() -> None:
    assert grade_route_partition(_metrics(success_rate=0.96), {"route_blocked": False}) == 1.0
    assert grade_route_partition(_metrics(success_rate=0.8), {"route_blocked": True}) == 0.0
