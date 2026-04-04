import json
import os
import re
from typing import Any

import httpx
from server.constants import (
    DEFAULT_BASELINE_TASK_ENUMS,
    NO_COMMAND_PROVIDED_SENTINEL,
    TASK_MAX_STEPS,
    TaskName,
)
from server.models import Action, Observation, StepResult

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")
BENCHMARK = "distributed-systems-debug-env"
MAX_STEPS_CAP = int(os.getenv("MAX_STEPS", "0"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

SYSTEM_PROMPT = """You have bash access to a distributed job processing pipeline that is experiencing a failure.
Use bash commands to investigate system behavior and narrow down likely fault conditions.
Standard Unix tools are available: ps, ls, cat, grep, tail, curl, jq, redis-cli, kill, sed.
Work iteratively across multiple steps; each response must provide the next bash command only.
Respond with compact JSON where `command` is required: {"command":"<bash command>","reasoning":"optional concise reason"}.
No markdown. No explanation outside JSON."""

TASK_SYMPTOMS: dict[TaskName, tuple[str, ...]] = {
    TaskName.CASCADING_TIMEOUT: (
        "Requests intermittently fail even when services appear up.",
        "Latency spikes sharply during traffic bursts.",
    ),
    TaskName.BYZANTINE_QUEUE_FAULT: (
        "Worker throughput degrades after specific jobs enter the queue.",
        "Queue backlog grows despite workers being alive.",
    ),
    TaskName.DISTRIBUTED_LOCK_STARVATION: (
        "One or more workers appear blocked for extended periods.",
        "Work completion remains low without full service outage.",
    ),
    TaskName.BACKPRESSURE_CASCADE: (
        "Queue depth trends upward over time under steady load.",
    ),
    TaskName.ROUTE_PARTITION: (
        "Gateway requests intermittently fail despite local process health.",
    ),
}


class DistributedDebugEnvClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=45.0)

    def close(self) -> None:
        self._client.close()

    def reset(self, task_name: str) -> Observation:
        response = self._client.post("/reset", params={"task_name": task_name})
        response.raise_for_status()
        return Observation.model_validate(response.json())

    def step(self, action: Action) -> StepResult:
        response = self._client.post("/step", json=action.model_dump())
        response.raise_for_status()
        return StepResult.model_validate(response.json())


def _parse_tasks() -> list[TaskName]:
    csv = os.getenv("TASKS_CSV", "").strip()
    if not csv:
        return list(DEFAULT_BASELINE_TASK_ENUMS)

    tasks: list[TaskName] = []
    for value in csv.split(","):
        task_str = value.strip()
        if not task_str:
            continue
        tasks.append(TaskName.parse(task_str))

    return tasks


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _single_line(text: str) -> str:
    return " ".join(text.replace("\t", " ").splitlines()).strip()


def _parse_action_payload(text: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, None

    if not isinstance(payload, dict):
        return None, None

    command_value = payload.get("command")
    command = command_value.strip() if isinstance(command_value, str) else ""
    if not command:
        return None, None

    reasoning_value = payload.get("reasoning")
    reasoning = reasoning_value.strip() if isinstance(reasoning_value, str) else ""
    return command, (reasoning or None)


def extract_action_payload(llm_response: str) -> tuple[str | None, str | None]:
    response = llm_response.strip()
    if not response:
        return None, None

    if response.startswith("```"):
        lines = response.split("\n")
        if len(lines) > 2:
            response = "\n".join(lines[1:-1]).strip()

    direct_command, direct_reasoning = _parse_action_payload(response)
    if direct_command:
        return direct_command, direct_reasoning

    for match in re.finditer(r"\{[^{}]*\}", response, flags=re.DOTALL):
        embedded_command, embedded_reasoning = _parse_action_payload(match.group(0))
        if embedded_command:
            return embedded_command, embedded_reasoning

    first_line = response.split("\n")[0].strip()
    return _parse_action_payload(first_line)


def extract_command(llm_response: str) -> str | None:
    return extract_action_payload(llm_response)[0]


def extract_reasoning(llm_response: str) -> str | None:
    return extract_action_payload(llm_response)[1]


def _sanitize_reasoning_for_step(reasoning: str) -> str:
    sanitized = _single_line(reasoning)
    sanitized = sanitized.replace(" reward=", " reward:")
    sanitized = sanitized.replace(" done=", " done:")
    sanitized = sanitized.replace(" error=", " error:")
    return sanitized[:160]


def _format_step_action(command: str, reasoning: str | None) -> str:
    action = _single_line(command)
    if not reasoning:
        return action

    sanitized_reasoning = _sanitize_reasoning_for_step(reasoning)
    if not sanitized_reasoning:
        return action
    return f"{action} | reasoning={sanitized_reasoning}"

def _task_symptom_block(task_name: TaskName) -> str:
    return "\n".join(f"- {symptom}" for symptom in TASK_SYMPTOMS[task_name])


def _attempt_history_block(attempt_history: list[dict[str, Any]]) -> str:
    if not attempt_history:
        return "- none"

    lines: list[str] = []
    for attempt in attempt_history:
        command = _single_line(str(attempt["command"]))[:120]
        reasoning = _single_line(str(attempt.get("reasoning") or ""))[:120]
        output_preview = _single_line(str(attempt.get("output") or ""))[:140]
        error = attempt.get("error")
        error_text = _single_line(str(error))[:80] if error else "none"
        line = f"- step {attempt['step']}: command={command}; error={error_text}"
        if reasoning:
            line = f"{line}; reasoning={reasoning}"
        if output_preview:
            line = f"{line}; output={output_preview}"
        lines.append(line)

    return "\n".join(lines)


def build_prompt(
    obs: Observation,
    step_num: int,
    task_name: TaskName,
    attempt_history: list[dict[str, Any]],
) -> str:
    return (
        f"Step {step_num}. Current system state:\n\n"
        "TASK SYMPTOMS:\n"
        f"{_task_symptom_block(task_name)}\n\n"
        "PREVIOUS ATTEMPTS:\n"
        f"{_attempt_history_block(attempt_history)}\n\n"
        "METRICS:\n"
        f"- Gateway success rate: {obs.metrics.gateway_success_rate:.1%}\n"
        f"- Gateway P99 latency: {obs.metrics.gateway_p99_latency_ms:.0f}ms\n"
        f"- Queue depth: {obs.metrics.queue_depth}\n"
        f"- Worker restarts: {obs.metrics.worker_restart_count}\n"
        f"- Consumer stall count: {obs.metrics.consumer_stall_count}\n\n"
        "SERVICE STATUS:\n"
        f"{obs.process_status}\n\n"
        "LATEST COMMAND OUTPUT:\n"
        f"{obs.command_output[:2000]}\n\n"
        "Solve this over multiple steps as needed. For this step, return only the single next bash command.\n"
        "Respond with compact JSON where command is required: {\"command\":\"<bash command>\",\"reasoning\":\"optional concise reason\"}."
    )


def _run_episode(client: Any, env: DistributedDebugEnvClient, task_name: TaskName) -> None:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    rewards: list[float] = []

    done = False
    step = 0
    last_error: str | None = None
    attempt_history: list[dict[str, Any]] = []

    print(f"[START] task={task_name.value} env={BENCHMARK} model={MODEL_NAME}", flush=True)

    task_budget = TASK_MAX_STEPS[task_name]
    max_steps = min(task_budget, MAX_STEPS_CAP) if MAX_STEPS_CAP > 0 else task_budget
    try:
        obs = env.reset(task_name=task_name.value)
        while not done and step < max_steps:
            next_step = step + 1
            user_prompt = build_prompt(obs, next_step, task_name, attempt_history)
            messages.append({"role": "user", "content": user_prompt})

            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=128,
            )

            raw_response = completion.choices[0].message.content or ""
            command, reasoning = extract_action_payload(raw_response)
            if not command:
                messages.append({"role": "assistant", "content": raw_response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "No command was provided. Respond with compact JSON where command is required: "
                            '{"command":"<bash command>","reasoning":"optional concise reason"}.'
                        ),
                    }
                )
                command = NO_COMMAND_PROVIDED_SENTINEL
                reasoning = None
            else:
                assistant_payload: dict[str, str] = {"command": command}
                if reasoning:
                    assistant_payload["reasoning"] = reasoning
                messages.append(
                    {"role": "assistant", "content": json.dumps(assistant_payload)}
                )

            result = env.step(Action(command=command))
            obs = result.observation
            rewards.append(result.reward)
            done = result.done

            error_value = result.info.get("error")
            last_error = None if error_value in (None, "", "None") else str(error_value)
            error_field = "null" if last_error is None else _single_line(last_error)
            attempt_history.append(
                {
                    "step": next_step,
                    "command": command,
                    "reasoning": reasoning,
                    "output": obs.command_output,
                    "error": last_error,
                }
            )

            print(
                f"[STEP]  step={next_step} action={_format_step_action(command, reasoning)} "
                f"reward={result.reward:.2f} done={_bool(done)} error={error_field}",
                flush=True,
            )
            step = next_step

    except Exception as exc:
        last_error = str(exc)
    finally:
        success = bool(done and rewards and rewards[-1] >= 0.95)
        rewards_csv = ",".join(f"{reward:.2f}" for reward in rewards)
        print(
            f"[END]   success={_bool(success)} steps={step} rewards={rewards_csv}",
            flush=True,
        )


def main() -> None:
    if not API_KEY:
        raise RuntimeError("HF_TOKEN (or API_KEY) must be set")

    tasks = _parse_tasks()

    from openai import OpenAI

    client = OpenAI(
        api_key=API_KEY,
        base_url=API_BASE_URL,
        timeout=30.0,
        max_retries=2,
    )
    env = DistributedDebugEnvClient(base_url=ENV_URL)

    try:
        for task_name in tasks:
            _run_episode(client, env, task_name)
    finally:
        env.close()


if __name__ == "__main__":
    main()
