from server.graders import (
    grade_backpressure_cascade,
    grade_byzantine_queue_fault,
    grade_cascading_timeout,
    grade_job_generator_runaway,
    grade_registry_corruption,
    grade_distributed_lock_starvation,
    grade_route_partition,
)
from server.models import SystemMetrics


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
    assert (
        grade_cascading_timeout(
            _metrics(success_rate=1.0), {"cascading_timeout_resolved": True}
        )
        == 0.99
    )
    assert (
        grade_cascading_timeout(
            _metrics(success_rate=1.0), {"cascading_timeout_resolved": False}
        )
        == 0.25
    )
    assert (
        grade_cascading_timeout(
            _metrics(success_rate=0.5), {"cascading_timeout_resolved": False}
        )
        == 0.125
    )


def test_grade_byzantine_queue_fault_cases() -> None:
    ctx = {"baseline_worker_restart_count": 3}
    assert grade_byzantine_queue_fault(_metrics(depth=0, restarts=3), ctx) == 0.99
    assert grade_byzantine_queue_fault(_metrics(depth=0, restarts=8), ctx) == 0.6
    assert grade_byzantine_queue_fault(_metrics(depth=40, restarts=10), ctx) == 0.01


def test_grade_distributed_lock_starvation_cases() -> None:
    ctx_locked = {"baseline_consumer_stall_count": 0, "lock_exists": True}
    ctx_unlocked = {"baseline_consumer_stall_count": 0, "lock_exists": False}

    assert (
        grade_distributed_lock_starvation(_metrics(depth=2, stalls=0), ctx_unlocked)
        == 0.99
    )
    assert (
        grade_distributed_lock_starvation(_metrics(depth=10, stalls=0), ctx_unlocked)
        == 0.6
    )
    assert (
        grade_distributed_lock_starvation(_metrics(depth=10, stalls=3), ctx_locked)
        == 0.01
    )


def test_grade_backpressure_cascade_continuous() -> None:
    assert grade_backpressure_cascade(_metrics(depth=0), {}) == 0.99
    assert grade_backpressure_cascade(_metrics(depth=100), {}) == 0.5
    assert grade_backpressure_cascade(_metrics(depth=200), {}) == 0.01


def test_grade_route_partition_threshold() -> None:
    assert (
        grade_route_partition(_metrics(success_rate=0.96), {"route_blocked": False})
        == 0.99
    )
    assert (
        grade_route_partition(_metrics(success_rate=0.8), {"route_blocked": True})
        == 0.01
    )


def test_grade_registry_corruption_thresholds() -> None:
    assert (
        grade_registry_corruption(
            _metrics(success_rate=0.99), {"registry_auth_matches_default": True}
        )
        == 0.99
    )
    assert (
        grade_registry_corruption(
            _metrics(success_rate=0.8), {"registry_auth_matches_default": True}
        )
        == 0.9
    )
    assert (
        grade_registry_corruption(
            _metrics(success_rate=1.0), {"registry_auth_matches_default": False}
        )
        == 0.3
    )


def test_grade_job_generator_runaway_thresholds() -> None:
    assert (
        grade_job_generator_runaway(
            _metrics(depth=4), {"job_generator_rate_resolved": True}
        )
        == 0.99
    )
    assert (
        grade_job_generator_runaway(
            _metrics(depth=20), {"job_generator_rate_resolved": True}
        )
        == 0.7
    )
    assert (
        grade_job_generator_runaway(
            _metrics(depth=20), {"job_generator_rate_resolved": False}
        )
        == 0.2
    )
