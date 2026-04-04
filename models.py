from typing import Any

from pydantic import BaseModel, Field, field_validator


class SystemMetrics(BaseModel):
    gateway_success_rate: float = Field(..., ge=0.0, le=1.0)
    gateway_p99_latency_ms: float = Field(..., ge=0.0)
    queue_depth: int = Field(..., ge=0)
    worker_restart_count: int = Field(..., ge=0)
    consumer_stall_count: int = Field(..., ge=0)


class Observation(BaseModel):
    command_output: str = Field(
        ..., description="stdout+stderr from the last executed command"
    )
    metrics: SystemMetrics
    process_status: dict[str, str] = Field(default_factory=dict)


class Action(BaseModel):
    command: str = Field(..., description="Single bash command to execute")

    @field_validator("command")
    @classmethod
    def command_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must not be empty")
        return value


class Reward(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)


class StepResult(BaseModel):
    observation: Observation
    reward: float = Field(..., ge=0.0, le=1.0)
    done: bool
    info: dict[str, Any] = Field(default_factory=dict)
