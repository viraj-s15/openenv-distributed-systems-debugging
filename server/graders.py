from typing import Any

from .constants import TaskName
from .models import SystemMetrics


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


def grade_cascading_timeout(metrics: SystemMetrics, context: dict[str, Any]) -> float:
    timeout_resolved = bool(context.get("cascading_timeout_resolved", False))
    if timeout_resolved and metrics.gateway_success_rate >= 0.99:
        return 1.0
    if not timeout_resolved:
        # Prevent instant pass while the injected timeout fault is still active.
        return _clamp(metrics.gateway_success_rate * 0.25)
    return _clamp(0.4 + metrics.gateway_success_rate * 0.4)


def grade_byzantine_queue_fault(metrics: SystemMetrics, context: dict[str, Any]) -> float:
    baseline_restart = int(context.get("baseline_worker_restart_count", 0))
    restart_delta = max(0, metrics.worker_restart_count - baseline_restart)

    if metrics.queue_depth == 0 and restart_delta <= 1:
        return 1.0
    if metrics.queue_depth == 0:
        return 0.6

    queue_component = max(0.0, 1.0 - metrics.queue_depth / 50.0)
    stability_penalty = min(0.4, restart_delta * 0.05)
    return _clamp(queue_component - stability_penalty)


def grade_distributed_lock_starvation(metrics: SystemMetrics, context: dict[str, Any]) -> float:
    lock_exists = bool(context.get("lock_exists", True))
    baseline_stall = int(context.get("baseline_consumer_stall_count", 0))
    stall_delta = max(0, metrics.consumer_stall_count - baseline_stall)

    if not lock_exists and metrics.queue_depth <= 3:
        return 1.0
    if not lock_exists:
        return 0.6

    # If lock still exists, reward slight progress only when stalls don't explode.
    return 0.2 if stall_delta <= 1 else 0.0


def grade_backpressure_cascade(metrics: SystemMetrics, _: dict[str, Any]) -> float:
    return _clamp(1.0 - (metrics.queue_depth / 200.0))


def grade_route_partition(metrics: SystemMetrics, context: dict[str, Any]) -> float:
    route_blocked = bool(context.get("route_blocked", True))
    if not route_blocked and metrics.gateway_success_rate >= 0.95:
        return 1.0
    if not route_blocked:
        return _clamp(metrics.gateway_success_rate)
    return 0.0


def grade_task(
    task_name: TaskName | str, metrics: SystemMetrics, context: dict[str, Any]
 ) -> float:
    task = TaskName.parse(task_name) if isinstance(task_name, str) else task_name

    if task is TaskName.CASCADING_TIMEOUT:
        return grade_cascading_timeout(metrics, context)
    if task is TaskName.BYZANTINE_QUEUE_FAULT:
        return grade_byzantine_queue_fault(metrics, context)
    if task is TaskName.DISTRIBUTED_LOCK_STARVATION:
        return grade_distributed_lock_starvation(metrics, context)
    if task is TaskName.BACKPRESSURE_CASCADE:
        return grade_backpressure_cascade(metrics, context)
    if task is TaskName.ROUTE_PARTITION:
        return grade_route_partition(metrics, context)
    return 0.0
